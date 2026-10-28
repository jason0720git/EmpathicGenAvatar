"""Check the actual attention math, not only importability, before inference."""
from importlib.metadata import version


def validate_joint_attention() -> dict:
    import torch
    from diffusers.models.attention_processor import Attention, JointAttnProcessor2_0

    installed = version("diffusers")
    if installed != "0.32.2":
        raise RuntimeError(f"LAM requires validated diffusers==0.32.2; found {installed}. Older joint attention silently ignores learned Q/K normalization.")
    attention = Attention(query_dim=8, added_kv_proj_dim=8, dim_head=4, heads=2,
                          out_dim=8, context_pre_only=False, bias=True,
                          processor=JointAttnProcessor2_0(), qk_norm="rms_norm")
    expected = ["norm_q", "norm_k", "norm_added_q", "norm_added_k"]
    observed = []
    hooks = [getattr(attention, name).register_forward_hook(
        lambda module, args, result, name=name: observed.append(name)) for name in expected]
    try:
        with torch.no_grad():
            sample, context = attention(torch.ones(1, 3, 8), encoder_hidden_states=torch.ones(1, 2, 8))
        if sorted(observed) != sorted(expected) or not torch.isfinite(sample).all() or not torch.isfinite(context).all():
            raise RuntimeError("Joint attention compatibility check failed: all four learned Q/K normalization layers must execute")
    finally:
        for hook in hooks:
            hook.remove()
    return {"compatible": True, "diffusers_version": installed, "checked_normalizations": observed}
