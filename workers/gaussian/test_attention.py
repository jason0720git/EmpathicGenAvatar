"""Regression for the silently incompatible Ditto-base Diffusers processor."""
import unittest

import torch
from diffusers.models.attention_processor import Attention, JointAttnProcessor2_0


class JointAttentionCompatibilityTest(unittest.TestCase):
    def test_all_checkpoint_qk_normalizations_are_used(self):
        attention = Attention(query_dim=8, added_kv_proj_dim=8, dim_head=4, heads=2,
                              out_dim=8, context_pre_only=False, bias=True,
                              processor=JointAttnProcessor2_0(), qk_norm="rms_norm")
        observed = []
        names = ["norm_q", "norm_k", "norm_added_q", "norm_added_k"]
        hooks = [getattr(attention, name).register_forward_hook(
            lambda module, args, result, name=name: observed.append(name)) for name in names]
        try:
            with torch.no_grad():
                sample, context = attention(torch.randn(1, 3, 8), encoder_hidden_states=torch.randn(1, 2, 8))
            self.assertCountEqual(observed, names, "Silently skipping learned normalization corrupts LAM geometry/opacity")
            self.assertTrue(torch.isfinite(sample).all())
            self.assertTrue(torch.isfinite(context).all())
        finally:
            for hook in hooks:
                hook.remove()


if __name__ == "__main__":
    unittest.main()
