#include "octree.hpp"
#include "taskloaf.hpp"

#include <cereal/types/vector.hpp>
#include <cereal/types/array.hpp>
#include "doctest.h"

#include <random>

namespace tectosaur {

inline std::ostream& operator<<(std::ostream& os, const Vec3& v) {
    os << "(" << v[0] << ", " << v[1] << ", " << v[2] << ")";
    return os;
}

Box bounding_box(const std::vector<Vec3>& pts) {
    if (pts.size() == 0) {
        return {{0,0,0}, {0,0,0}};
    }
    auto min_corner = pts[0];
    auto max_corner = pts[0];
    for (size_t i = 1; i < pts.size(); i++) {
        for (size_t d = 0; d < 3; d++) {
            min_corner[d] = std::min(min_corner[d], pts[i][d]);
            max_corner[d] = std::max(max_corner[d], pts[i][d]);
        }
    }
    Vec3 center;
    Vec3 half_width;
    for (size_t d = 0; d < 3; d++) {
        center[d] = (max_corner[d] + min_corner[d]) / 2.0;
        half_width[d] = (max_corner[d] - min_corner[d]) / 2.0;
    }
    return {center, half_width};
}

Box bounding_cube(const std::vector<Vec3>& pts) {
    auto box = bounding_box(pts);
    auto r = std::max(std::max(box.half_width[0], box.half_width[1]), box.half_width[2]);
    return {box.center, {r,r,r}};
}

TEST_CASE("bounding_box") {
    auto b = bounding_box({{0,0,0},{2,2,2}});
    for (int d = 0; d < 3; d++) {
        CHECK(b.center[d] == 1.0); CHECK(b.half_width[d] == 1.0);
    }
}

TEST_CASE("bounding box no pts") {
    auto b = bounding_box({}); (void)b;
}

int find_containing_subcell(const Box& b, const Vec3& pt) {
    int child_idx = 0;
    for (size_t d = 0; d < 3; d++) {
        if (pt[d] > b.center[d]) {
            child_idx++; 
        }
        if (d < 2) {
            child_idx = child_idx << 1;
        }
    }
    return child_idx;
}

TEST_CASE("subcell") {
    CHECK(find_containing_subcell({{0,0,0},{1,1,1}}, {-0.5,0.5,0.5}) == 3);
    CHECK(find_containing_subcell({{0,0,0},{1,1,1}}, {0.5,-0.5,0.5}) == 5);
    CHECK(find_containing_subcell({{0,0,0},{1,1,1}}, {0.5,0.5,-0.5}) == 6);
    CHECK(find_containing_subcell({{0,0,0},{1,1,1}}, {0.5,0.5,0.5}) == 7);
}

Box get_subcell(const Box& parent, int idx) {
    auto new_halfwidth = parent.half_width;
    auto new_center = parent.center;
    for (int d = 2; d >= 0; d--) {
        new_halfwidth[d] /= 2.0;
        auto which_side = idx % 2;
        idx = idx >> 1;
        new_center[d] += ((static_cast<double>(which_side) * 2) - 1) * new_halfwidth[d];
    }
    return {new_center, new_halfwidth};
}

bool in_box(const Box& b, const Vec3& pt)
{
    bool in = true;
    for (size_t d = 0; d < 3; d++) {
        auto sep = std::fabs(pt[d] - b.center[d]);
        in = in && (sep <= b.half_width[d]);
    }
    return in;
}

TEST_CASE("get subcell") {
    thread_local std::random_device rd;
    thread_local std::mt19937 gen(rd());
    std::uniform_real_distribution<> dis(-1, 1);
    Box parent{{0,0,0},{1,1,1}};
    for (int i = 0; i < 100; i++) {
        Vec3 pt = {dis(gen), dis(gen), dis(gen)};
        auto idx = find_containing_subcell(parent, pt);
        auto subcell = get_subcell(parent, idx);
        REQUIRE(in_box(subcell, pt));
    }
}

tl::future<OctreeNode::Ptr> make_node(size_t max_pts_per_cell, 
    Box parent_bounds, NodeData data) 
{
    return tl::task(
        [=] (NodeData& data) {
            return std::make_shared<OctreeNode>(
                max_pts_per_cell, parent_bounds, std::move(data)
            ); 
        },
        std::move(data)
    );  
}

OctreeNode::OctreeNode(size_t max_pts_per_cell, Box parent_bounds, NodeData in_data) {
    //This is probably the bottleneck if any future performance is needed
    //Parallelizing the bounding box construction for the near-root nodes
    //would be useful.
    if (in_data.pts.size() <= 1) {
        auto hw = parent_bounds.half_width;
        for (int d = 0; d < 3; d++) {
            hw[d] /= 100; 
        }
        auto center = (in_data.pts.size() == 0) ? parent_bounds.center: in_data.pts[0];
        bounds = {center, hw};
    } else {
        bounds = bounding_cube(in_data.pts);
    }

    if (in_data.pts.size() <= max_pts_per_cell) {
        is_leaf = true;
        data = std::move(in_data);
        return;
    }

    data.original_indices = std::move(in_data.original_indices);

    std::array<NodeData,8> child_data{};
    for (size_t i = 0; i < in_data.pts.size(); i++) {
        auto child_idx = find_containing_subcell(bounds, in_data.pts[i]);
        child_data[child_idx].pts.push_back(std::move(in_data.pts[i]));
        child_data[child_idx].normals.push_back(std::move(in_data.normals[i]));
        child_data[child_idx].original_indices.push_back(data.original_indices[i]);
    }

    for (int child_idx = 0; child_idx < 8; child_idx++) {
        children[child_idx] = make_node(
            max_pts_per_cell, bounds, std::move(child_data[child_idx])
        );
    }
}

Octree::Octree(size_t max_pts_per_cell, NodeData data) {
    root = make_node(max_pts_per_cell, {{0, 0, 0}, {1, 1, 1}}, std::move(data));
}

tl::future<int> total_children_helper(OctreeNode::Ptr& n) {
    if (n->is_leaf) {
        return tl::ready(int(n->data.pts.size()));
    }
    tl::future<int> sum = tl::ready(0);
    for (int i = 0; i < 8; i++) {
        sum = n->children[i].then(total_children_helper)
            .unwrap()
            .then([] (tl::future<int> val, int x) {
                return val.then([=] (int y) { return x + y; });
            }, sum)
            .unwrap();
    }
    return sum;
}

int n_total_children(Octree& o) {
    return o.root.then([] (OctreeNode::Ptr& n) {
        return total_children_helper(n);
    }).unwrap().get();
}

} //end namespace tectosaur