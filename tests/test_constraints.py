from tectosaur.constraints import *
import numpy as np

def test_rearrange_constraint_eq():
    eqtn = ConstraintEQ([Term(3,0),Term(-1,1),Term(4,2)], 13.7)
    rearr = isolate_term_on_lhs(eqtn, 2)
    assert(rearr ==
        IsolatedTermEQ(2, [Term(-3.0 / 4.0, 0), Term(1.0 / 4.0, 1)], 13.7 / 4.0))

def subs_test(victim, sub_in, correct):
    in_rearr = isolate_term_on_lhs(sub_in, 0)
    result = substitute(victim, 0, in_rearr)
    assert(result == correct)

def test_combine_terms():
    assert(combine_terms(ConstraintEQ([Term(1, 1), Term(2, 1)], 0.0)) ==
            ConstraintEQ([Term(3,1)], 0.0))

def test_subs_rhs():
    eqtn0 = ConstraintEQ([Term(1,1), Term(3,1)], 4.0)
    eqtn1 = ConstraintEQ([Term(1,1)], 2.0)
    correct = ConstraintEQ([Term(3,1)], 2.0)
    subs_test(eqtn0, eqtn1, correct)

def test_filter_zero():
    assert(filter_zero_terms(ConstraintEQ([Term(1, 0), Term(0, 1)], 0.0)) ==
        ConstraintEQ([Term(1, 0)], 0.0))

def test_constraint_matrix():
    cs = [ConstraintEQ([Term(1, 0), Term(-1, 1)], 0.0)]
    cm,rhs = build_constraint_matrix(cs, 3)
    assert(cm.shape == (3, 2))
    np.testing.assert_almost_equal(cm.todense(), [[1, 0], [1, 0], [0, 1]])

def test_constraint_matrix_harder():
    cs = [
        ConstraintEQ([Term(1, 5), Term(-1, 1)], 0.0),
        ConstraintEQ([Term(1, 3), Term(0.25, 0)], 0.0),
        ConstraintEQ([Term(1, 2), Term(0.5, 3), Term(0.5, 4)], 0.0)
    ]
    cm,rhs = build_constraint_matrix(cs, 7)
    assert(cm.shape == (7, 4))
    correct = [
        [1,0,0,0],[0,1,0,0],[0,0,1,0], [-0.25,0,0,0],
        [0.25,0,-2,0],[0,1,0,0],[0,0,0,1]
    ]
    np.testing.assert_almost_equal(cm.todense(), correct)

def test_constraint_matrix_rhs():
    cs = [
        ConstraintEQ([Term(1, 5), Term(-1, 1)], 0.0),
        ConstraintEQ([Term(1, 3), Term(0.25, 0)], 1.0),
        ConstraintEQ([Term(1, 2), Term(0.5, 3), Term(0.5, 4)], 2.0)
    ]
    cm, rhs = build_constraint_matrix(cs, 7)
    np.testing.assert_almost_equal(rhs, [0,0,0,1.0,3.0,0,0])

def test_free_edge_constraints():
    cs = free_edge_constraints([[0,1,2],[0,2,3],[0,3,4],[0,4,1]])
    dofs = [c.terms[0].dof for c in cs]
    assert(0 not in dofs)
    assert(len(dofs) == 8 * 3)
