import unittest
import numpy as np
from measure_identity import align_eyes
from fit_identity_asset import make_warp


class IdentityFitTest(unittest.TestCase):
    def fixture(self):
        rng=np.random.default_rng(5)
        points=rng.uniform([150,150],[300,340],(68,2))
        points[36:42]=rng.uniform([170,180],[200,200],(6,2))
        points[42:48]=rng.uniform([250,180],[280,200],(6,2))
        return points

    def test_alignment_removes_only_similarity_not_face_shape(self):
        p=self.fixture(); a=.15;R=np.array([[np.cos(a),-np.sin(a)],[np.sin(a),np.cos(a)]])
        q=p@R.T*1.7+[22,41]
        aligned,_=align_eyes(p,q)
        np.testing.assert_allclose(aligned,q,atol=1e-10)
        q[48:68,1]+=5
        aligned,_=align_eyes(p,q)
        self.assertGreater(np.linalg.norm(aligned[48:68]-q[48:68]),10)

    def test_zero_residual_is_identity_and_large_request_is_bounded(self):
        p=self.fixture();camera={'position':[0,0,1],'target':[0,0,0],'up':[0,1,0],'fov':24}
        m={'render_landmarks':p.tolist(),'target_landmarks':p.tolist(),'render_size':[450,450]}
        points=np.array([[0,0,.07],[.01,-.04,.05],[0,-.15,-.04]])
        np.testing.assert_allclose(make_warp(m,camera)(points),points,atol=1e-12)
        m['target_landmarks']=(p+[80,-80]).tolist()
        transformed=make_warp(m,camera)(points)
        self.assertLessEqual(np.linalg.norm(transformed-points,axis=1).max(),.00600001)
        np.testing.assert_array_equal(transformed[-1],points[-1])


if __name__=='__main__':unittest.main()
