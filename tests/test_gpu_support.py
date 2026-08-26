"""A GPU that is detected must actually be used.

The failure this pins down had three parts, all of which ended the same way:
the card was found, the badge went green, and every job ran on the processor.

  * ctranslate2 refuses float16 below compute capability 7.0, so on Pascal
    cards (GTX 10xx) the only GPU attempt the loader knew about always failed;
  * cuBLAS and cuDNN do not come with the NVIDIA driver, and the installer step
    that adds them aborted before it ran;
  * the badge asked nvidia-smi, which only proves a driver is installed.
"""

import sys
import types
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.modules.setdefault("webview", types.SimpleNamespace(FileDialog=object))

import app
import transcribe

# What ctranslate2 reports on a GTX 1070 and on a modern card.
PASCAL = {"int8", "int8_float32", "float32"}
AMPERE = {"int8", "int8_float16", "int8_float32", "float16", "float32"}

FP16_REFUSED = ("Requested float16 compute type, but the target device or "
                "backend do not support efficient float16 computation.")


@contextmanager
def gpu_reporting(supported=None, error=None):
    """Stand in for the installed ctranslate2, which the tests never have."""
    def get_supported_compute_types(device):
        if error is not None:
            raise error
        return supported
    fake = types.SimpleNamespace(get_supported_compute_types=get_supported_compute_types)
    with mock.patch.dict(sys.modules, {"ctranslate2": fake}):
        yield


class ComputeTypeSelectionTests(unittest.TestCase):
    def test_pascal_card_is_offered_a_gpu_compute_type(self):
        """float16 is the one thing such a card cannot do - it is not unusable."""
        with gpu_reporting(PASCAL):
            self.assertEqual(["int8_float32", "float32"], transcribe.cuda_compute_types())

    def test_modern_card_still_prefers_float16(self):
        with gpu_reporting(AMPERE):
            self.assertEqual("float16", transcribe.cuda_compute_types()[0])

    def test_unusable_gpu_is_reported_as_none(self):
        """None distinguishes "cannot ask" from "supports nothing useful"."""
        with gpu_reporting(error=RuntimeError("no CUDA devices")):
            self.assertIsNone(transcribe.cuda_compute_types())


class DeviceFallbackTests(unittest.TestCase):
    def setUp(self):
        self.tried = []

    def loader(self, refuse=("float16",)):
        def _load(model_size, device, compute_type, download_root):
            self.tried.append((device, compute_type))
            if device == "cuda" and compute_type in refuse:
                raise ValueError(FP16_REFUSED)
            return object()
        return _load

    def load(self, prefer_device, supported=PASCAL, refuse=("float16",)):
        with gpu_reporting(supported), \
                mock.patch.object(transcribe, "_load_model", self.loader(refuse)):
            return transcribe.load_model_with_fallback(
                model_size="small", prefer_device=prefer_device, log=lambda *_: None,
            )

    def test_pascal_card_runs_on_the_gpu_rather_than_the_cpu(self):
        _, device, compute_type = self.load("auto")

        self.assertEqual(("cuda", "int8_float32"), (device, compute_type))
        self.assertNotIn("cpu", [d for d, _ in self.tried])

    def test_forced_gpu_does_not_give_up_after_float16(self):
        """"Только GPU (CUDA)" used to fail outright on these cards."""
        _, device, compute_type = self.load("cuda")

        self.assertEqual(("cuda", "int8_float32"), (device, compute_type))

    def test_cpu_remains_the_last_resort(self):
        _, device, compute_type = self.load(
            "auto", refuse=("float16", "int8_float16", "int8_float32", "float32"),
        )

        self.assertEqual(("cpu", "int8"), (device, compute_type))

    def test_cpu_only_never_touches_the_gpu(self):
        self.load("cpu")

        self.assertEqual([("cpu", "int8")], self.tried)


class MissingLibraryTests(unittest.TestCase):
    def test_libraries_that_will_not_load_are_named(self):
        """Otherwise a missing DLL shows up as a failed job, not as a cause."""
        with mock.patch.object(transcribe.os, "name", "nt"), \
                mock.patch.object(transcribe, "_can_load_library", return_value=False):
            self.assertEqual(["cuBLAS", "cuDNN"], transcribe.missing_cuda_libraries())

    def test_loadable_libraries_leave_nothing_to_report(self):
        with mock.patch.object(transcribe.os, "name", "nt"), \
                mock.patch.object(transcribe, "_can_load_library", return_value=True):
            self.assertEqual([], transcribe.missing_cuda_libraries())


class GpuBadgeTests(unittest.TestCase):
    def setUp(self):
        self.api = app.Api.__new__(app.Api)

    def gpu_info(self, card="NVIDIA GeForce GTX 1070", compute_types=None, missing=()):
        result = types.SimpleNamespace(
            returncode=0 if card else 1, stdout=(card + "\n") if card else "")
        with mock.patch.object(app.subprocess, "run", return_value=result), \
                mock.patch.object(app.transcribe_mod, "cuda_compute_types",
                                  return_value=compute_types), \
                mock.patch.object(app.transcribe_mod, "missing_cuda_libraries",
                                  return_value=list(missing)):
            return self.api.get_gpu_info()

    def test_working_card_reports_the_compute_type_it_will_use(self):
        info = self.gpu_info(compute_types=["int8_float32", "float32"])

        self.assertTrue(info["usable"])
        self.assertEqual("int8_float32", info["compute_type"])
        self.assertIsNone(info["reason"])

    def test_detected_card_without_cuda_libraries_is_not_reported_as_usable(self):
        """The green light over CPU-speed work is what hid the whole problem."""
        info = self.gpu_info(compute_types=["float16"], missing=["cuDNN"])

        self.assertTrue(info["available"])
        self.assertFalse(info["usable"])
        self.assertIn("cuDNN", info["reason"])
        self.assertIn("setup.bat", info["reason"])

    def test_card_cuda_cannot_see_is_not_reported_as_usable(self):
        info = self.gpu_info(compute_types=None)

        self.assertFalse(info["usable"])
        self.assertTrue(info["reason"])

    def test_machine_without_a_card_reports_nothing_to_use(self):
        info = self.gpu_info(card=None)

        self.assertFalse(info["available"])
        self.assertFalse(info["usable"])
        self.assertIsNone(info["name"])


class InstallerCudaStepTests(unittest.TestCase):
    """The step that installs the libraries has to survive its own probe."""

    def setUp(self):
        self.script = (ROOT / "setup.ps1").read_text(encoding="utf-8-sig")

    def test_python_is_never_run_with_its_errors_redirected(self):
        """PowerShell turns a redirected native command's stderr into a
        NativeCommandError, and ErrorActionPreference is Stop: the traceback
        from probing for a library that is not there killed the installer."""
        redirected = [line.strip() for line in self.script.splitlines()
                      if "$Py" in line and "2>" in line]

        self.assertEqual([], redirected)

    def test_both_runtime_libraries_are_installed(self):
        """ctranslate2 needs cuDNN as well as cuBLAS; neither is in the driver."""
        self.assertIn("nvidia-cublas-cu12", self.script)
        self.assertIn("nvidia-cudnn-cu12", self.script)


if __name__ == "__main__":
    unittest.main()
