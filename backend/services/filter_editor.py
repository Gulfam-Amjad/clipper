"""Filter editing service for VideoClipper.

This module validates user-provided filter values, builds an ffmpeg filter chain,
and applies the requested visual changes to a clip.
"""

import logging
import subprocess


logger = logging.getLogger(__name__)


# Default filter values used when the frontend does not provide a setting.
DEFAULT_FILTERS = {
	"brightness": 0.0,
	"contrast": 1.0,
	"saturation": 1.0,
	"hue": 0,
	"sharpness": 0.0,
	"vignette": 0.0,
	"fade_in": True,
	"fade_out": True,
}


# Preset filter collections used by the frontend preset dropdown.
FILTER_PRESETS = {
	"original": {
		"brightness": 0.0,
		"contrast": 1.0,
		"saturation": 1.0,
		"hue": 0,
		"sharpness": 0.0,
		"vignette": 0.0,
	},
	"cinematic": {
		"brightness": 0.02,
		"contrast": 1.15,
		"saturation": 1.1,
		"hue": 5,
		"sharpness": 0.4,
		"vignette": 0.6,
	},
	"vibrant": {
		"brightness": 0.05,
		"contrast": 1.1,
		"saturation": 1.6,
		"hue": 0,
		"sharpness": 0.5,
		"vignette": 0.3,
	},
	"cool": {
		"brightness": 0.0,
		"contrast": 1.05,
		"saturation": 1.1,
		"hue": -15,
		"sharpness": 0.3,
		"vignette": 0.4,
	},
	"warm": {
		"brightness": 0.04,
		"contrast": 1.08,
		"saturation": 1.2,
		"hue": 12,
		"sharpness": 0.3,
		"vignette": 0.3,
	},
	"dramatic": {
		"brightness": -0.05,
		"contrast": 1.4,
		"saturation": 0.8,
		"hue": 0,
		"sharpness": 0.8,
		"vignette": 0.8,
	},
	"soft": {
		"brightness": 0.08,
		"contrast": 0.9,
		"saturation": 1.1,
		"hue": 3,
		"sharpness": 0.0,
		"vignette": 0.2,
	},
}


# Clamp helper used by validation so bad inputs do not leak into ffmpeg.
def _clamp(value: object, minimum: float, maximum: float, fallback: float) -> float:
	try:
		numeric_value = float(value)
		return max(minimum, min(maximum, numeric_value))
	except Exception:
		return fallback


# Convert booleans and truthy values into a reliable True/False value.
def _to_bool(value: object, fallback: bool) -> bool:
	try:
		if isinstance(value, bool):
			return value
		if value is None:
			return fallback
		if isinstance(value, str):
			return value.strip().lower() in {"1", "true", "yes", "on"}
		return bool(value)
	except Exception:
		return fallback


# Normalize a filter dictionary so the rest of the module can rely on all keys.
def validate_filters(filters: dict) -> dict:
	try:
		logger.debug("Validating filters: %s", filters)
		cleaned_filters = dict(DEFAULT_FILTERS)
		provided_filters = filters or {}

		# Clamp numeric controls to the supported ffmpeg ranges.
		cleaned_filters["brightness"] = _clamp(
			provided_filters.get("brightness", DEFAULT_FILTERS["brightness"]),
			-0.5,
			0.5,
			DEFAULT_FILTERS["brightness"],
		)
		cleaned_filters["contrast"] = _clamp(
			provided_filters.get("contrast", DEFAULT_FILTERS["contrast"]),
			0.5,
			2.0,
			DEFAULT_FILTERS["contrast"],
		)
		cleaned_filters["saturation"] = _clamp(
			provided_filters.get("saturation", DEFAULT_FILTERS["saturation"]),
			0.0,
			3.0,
			DEFAULT_FILTERS["saturation"],
		)
		cleaned_filters["hue"] = int(
			_clamp(
				provided_filters.get("hue", DEFAULT_FILTERS["hue"]),
				-180,
				180,
				DEFAULT_FILTERS["hue"],
			)
		)
		cleaned_filters["sharpness"] = _clamp(
			provided_filters.get("sharpness", DEFAULT_FILTERS["sharpness"]),
			0.0,
			1.5,
			DEFAULT_FILTERS["sharpness"],
		)
		cleaned_filters["vignette"] = _clamp(
			provided_filters.get("vignette", DEFAULT_FILTERS["vignette"]),
			0.0,
			1.0,
			DEFAULT_FILTERS["vignette"],
		)

		# Normalize fade toggles without raising on bad input.
		cleaned_filters["fade_in"] = _to_bool(
			provided_filters.get("fade_in", DEFAULT_FILTERS["fade_in"]),
			DEFAULT_FILTERS["fade_in"],
		)
		cleaned_filters["fade_out"] = _to_bool(
			provided_filters.get("fade_out", DEFAULT_FILTERS["fade_out"]),
			DEFAULT_FILTERS["fade_out"],
		)

		logger.debug("Validated filters: %s", cleaned_filters)
		return cleaned_filters
	except Exception:
		logger.exception("Failed to validate filters; returning defaults")
		return dict(DEFAULT_FILTERS)


# Build the ffmpeg filter chain from cleaned filter values.
def build_filter_string(filters: dict, clip_duration: float) -> str:
	try:
		logger.debug("Building filter string for duration %.2f with filters: %s", clip_duration, filters)
		cleaned_filters = validate_filters(filters)
		active_filters: list[str] = []

		# Add the base eq filter first so brightness, contrast, and saturation apply together.
		eq_filter = (
			f"eq=brightness={cleaned_filters['brightness']}:"
			f"contrast={cleaned_filters['contrast']}:"
			f"saturation={cleaned_filters['saturation']}"
		)
		active_filters.append(eq_filter)

		# Add hue shift only when the value is non-zero.
		hue_value = int(cleaned_filters["hue"])
		if hue_value != 0:
			active_filters.append(f"hue=h={hue_value}")

		# Add unsharp sharpening only when the strength is positive.
		sharpness = float(cleaned_filters["sharpness"])
		if sharpness > 0:
			active_filters.append(f"unsharp=5:5:{sharpness}:5:5:0.0")

		# Add a vignette effect only when the strength is positive.
		vignette = float(cleaned_filters["vignette"])
		if vignette > 0:
			strength = vignette * (3.14159 / 4)
			active_filters.append(f"vignette={strength:.4f}")

		# Add a fade-in at the start only when enabled.
		if cleaned_filters["fade_in"]:
			active_filters.append("fade=t=in:st=0:d=0.3")

		# Add a fade-out near the end only when enabled.
		if cleaned_filters["fade_out"]:
			fade_start = max(0, float(clip_duration) - 0.4)
			active_filters.append(f"fade=t=out:st={fade_start:.2f}:d=0.4")

		# Return passthrough when there is nothing to apply.
		if not active_filters:
			logger.debug("No active filters found; returning passthrough null filter")
			return "null"

		# Join the active filters into the final ffmpeg chain.
		filter_string = ",".join(active_filters)
		logger.debug("Built filter string: %s", filter_string)
		return filter_string
	except Exception:
		logger.exception("Failed to build filter string")
		return "null"


# Return the preset definitions used by the frontend.
def get_filter_presets() -> dict:
	try:
		logger.debug("Returning filter presets")
		return {name: dict(values) for name, values in FILTER_PRESETS.items()}
	except Exception:
		logger.exception("Failed to return filter presets")
		return {}


# Apply the requested filter chain to a video clip using ffmpeg.
def apply_filters(input_path: str, output_path: str, filters: dict, clip_duration: float) -> str:
	try:
		# Build and log the final filter string before invoking ffmpeg.
		filter_string = build_filter_string(filters, clip_duration)
		logger.info("Applying filter string to %s: %s", input_path, filter_string)

		# Ensure the destination directory exists before writing the output file.
		from pathlib import Path

		Path(output_path).parent.mkdir(parents=True, exist_ok=True)

		# Build the ffmpeg command using a safe argument list.
		command = [
			"ffmpeg",
			"-y",
			"-i",
			input_path,
			"-vf",
			filter_string,
			"-c:v",
			"libx264",
			"-preset",
			"fast",
			"-crf",
			"20",
			"-c:a",
			"copy",
			output_path,
		]

		# Run ffmpeg and capture output so any failure can be reported clearly.
		logger.debug("Running ffmpeg command: %s", " ".join(command))
		result = subprocess.run(command, capture_output=True, text=True)

		# Raise a runtime error if ffmpeg reported a failure.
		if result.returncode != 0:
			error_message = result.stderr.strip() or result.stdout.strip() or "unknown ffmpeg error"
			logger.error("ffmpeg filter application failed: %s", error_message)
			raise RuntimeError(f"ffmpeg failed: {error_message}")

		# Confirm success in the logs and return the destination path.
		logger.info("Filters applied successfully: %s", output_path)
		return output_path
	except Exception as exc:
		logger.exception("Failed to apply filters")
		if isinstance(exc, RuntimeError):
			raise
		raise RuntimeError(f"Failed to apply filters: {exc}") from exc


if __name__ == "__main__":
	logger.info("filter_editor.py loaded OK")
