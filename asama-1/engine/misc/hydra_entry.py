import argparse
import os
import sys
from datetime import datetime
from typing import Any, Callable, Dict, List

try:
    import hydra
    from omegaconf import DictConfig, OmegaConf
    _HYDRA_IMPORT_ERROR = None
except ModuleNotFoundError as exc:
    hydra = None
    DictConfig = Any
    OmegaConf = None
    _HYDRA_IMPORT_ERROR = exc


def _resolve_cfg_path(cfg_path: str) -> str:
    if os.path.isabs(cfg_path):
        return cfg_path

    cwd_candidate = os.path.abspath(cfg_path)
    if os.path.isfile(cwd_candidate):
        return cwd_candidate

    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    repo_candidate = os.path.join(repo_root, cfg_path)
    if os.path.isfile(repo_candidate):
        return repo_candidate

    return cfg_path


def _infer_output_dir(defaults: Dict[str, Any]) -> str:
    # 1) Try to read from the training yaml pointed by `config` / `cfg`.
    cfg_path = defaults.get("config") or defaults.get("cfg")
    if isinstance(cfg_path, str):
        cfg_path = _resolve_cfg_path(cfg_path)
    if isinstance(cfg_path, str) and os.path.isfile(cfg_path):
        try:
            import yaml

            with open(cfg_path, "r", encoding="utf-8") as handle:
                raw_cfg = yaml.safe_load(handle) or {}
            output_dir = raw_cfg.get("output_dir")
            if output_dir:
                return str(output_dir)
        except Exception:
            pass

    # 2) Fall back to launcher defaults.
    if defaults.get("output_dir"):
        return str(defaults["output_dir"])

    # 3) Safe fallback.
    return "hydra_outputs"


def _default_hydra_cfg(job_name: str, output_dir: str) -> Dict[str, Any]:
    return {
        "hydra": {
            "job": {
                "name": job_name,
                "chdir": False,
            },
            "run": {
                "dir": output_dir,
            },
            "sweep": {
                "dir": f"{output_dir}/multirun/${{hydra.job.name}}/${{now:%Y-%m-%d}}/${{now:%H-%M-%S}}",
                "subdir": "${hydra.job.num}",
            },
            "output_subdir": ".hydra/${hydra.job.name}_${now:%Y-%m-%d_%H-%M-%S}",
        }
    }


def _has_cli_override(argv: List[str], key: str) -> bool:
    return any(
        arg.startswith(f"{key}=")
        or arg.startswith(f"+{key}=")
        or arg.startswith(f"++{key}=")
        for arg in argv
    )


def run_with_hydra(
    main_fn: Callable[[argparse.Namespace], None],
    defaults: Dict[str, Any],
    job_name: str,
) -> None:
    if hydra is None or OmegaConf is None:
        raise ModuleNotFoundError(
            "Hydra integration requires `hydra-core` and `omegaconf`. "
            "Install with: pip install hydra-core omegaconf"
        ) from _HYDRA_IMPORT_ERROR

    resolved_output_dir = _infer_output_dir(defaults)
    base_defaults = dict(defaults)
    base_defaults["output_dir"] = resolved_output_dir

    injected_overrides = [
        ("hydra.job.name", job_name),
        ("hydra.job.chdir", "False"),
        ("hydra.run.dir", resolved_output_dir),
        ("hydra.sweep.dir", f"{resolved_output_dir}/multirun/${{hydra.job.name}}/${{now:%Y-%m-%d}}/${{now:%H-%M-%S}}"),
        ("hydra.sweep.subdir", "${hydra.job.num}"),
        ("hydra.output_subdir", ".hydra/${hydra.job.name}_${now:%Y-%m-%d_%H-%M-%S}"),
    ]

    original_argv = list(sys.argv)
    for key, value in injected_overrides:
        if not _has_cli_override(sys.argv, key):
            sys.argv.append(f"{key}={value}")

    base_cfg = OmegaConf.merge(
        OmegaConf.create(base_defaults),
        OmegaConf.create(_default_hydra_cfg(job_name, resolved_output_dir)),
    )

    @hydra.main(version_base=None, config_path=None, config_name=None)
    def _entry(cfg: DictConfig) -> None:
        merged_cfg = OmegaConf.merge(base_cfg, cfg)
        runtime_cfg = OmegaConf.masked_copy(merged_cfg, [k for k in merged_cfg.keys() if k != "hydra"])
        args_dict = OmegaConf.to_container(runtime_cfg, resolve=True)

        # Persist experiment config snapshot (fully merged training YAML).
        output_dir = str(args_dict.get("output_dir", resolved_output_dir))
        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        snapshot_dir = os.path.join(output_dir, "hydra_configs", f"{job_name}_{timestamp}")
        try:
            os.makedirs(snapshot_dir, exist_ok=True)

            # Save the fully merged training YAML (resolves __include__ chain).
            import yaml
            from engine.core.yaml_utils import load_config
            training_cfg_path = str(args_dict.get("config") or args_dict.get("cfg") or "")
            if training_cfg_path:
                training_cfg_path = _resolve_cfg_path(training_cfg_path)
            if training_cfg_path and os.path.isfile(training_cfg_path):
                full_training_cfg = load_config(training_cfg_path, {})
                full_training_cfg.pop("__include__", None)
                with open(os.path.join(snapshot_dir, "config.yaml"), "w") as f:
                    yaml.dump(full_training_cfg, f, default_flow_style=False, allow_unicode=True)
            else:
                OmegaConf.save(runtime_cfg, os.path.join(snapshot_dir, "config.yaml"), resolve=True)

            # Save Hydra metadata and CLI overrides.
            OmegaConf.save(merged_cfg.hydra, os.path.join(snapshot_dir, "hydra.yaml"), resolve=False)
            overrides = [arg for arg in sys.argv[1:] if "=" in arg]
            with open(os.path.join(snapshot_dir, "overrides.yaml"), "w") as f:
                for o in overrides:
                    f.write(f"- {o}\n")

            # Save launcher args (hp_tuning params, etc.).
            with open(os.path.join(snapshot_dir, "args.yaml"), "w") as f:
                yaml.dump(args_dict, f, default_flow_style=False, allow_unicode=True)

            print(f"[Hydra] Config snapshot saved to: {snapshot_dir}")
        except Exception as exc:
            import traceback
            print(f"[Hydra] WARNING: Failed to save config snapshot to {snapshot_dir}: {exc}")
            traceback.print_exc()

        main_fn(argparse.Namespace(**args_dict))

    try:
        _entry()
    finally:
        sys.argv = original_argv
