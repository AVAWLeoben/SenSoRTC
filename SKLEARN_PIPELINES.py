# -*- coding: utf-8 -*-
"""
SKLearn NIR pipelines for SenSoRTC.

Supports mixed training inputs:
    - EVK SQALAR .mat files
    - SenSoRTC .npy raw spectral chunks
    - compressed .npz spectral arrays
    - Excel .xlsx/.xlsm files containing valid spectra for one class

Canonical spectral cube layout:
    (width, bands, lines), e.g. (312, 220, n_lines)

Training format after loading:
    X = (n_spectra, bands)
    y = (n_spectra,)

Design:
    NIRPipelineBase contains reusable loading/training/evaluation/saving logic.
    Concrete subclasses only define build_pipeline().
"""

from pathlib import Path

import joblib
import numpy as np
from scipy.io import loadmat

from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.neural_network import MLPClassifier
from sklearn.svm import SVC, LinearSVC
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, confusion_matrix

from scipy_transformer_adapter import SavGolTransformer


class NIRPipelineBase:
    """Base class for SenSoRTC/EVK NIR sklearn classifiers."""

    COMMON_BAND_COUNTS = (220,)

    def __init__(
        self,
        window_length=15,
        polyorder=2,
        deriv=1,
        random_state=42,
    ):
        self.window_length = window_length
        self.polyorder = polyorder
        self.deriv = deriv
        self.random_state = random_state

        self.X_train, self.X_test = None, None
        self.y_train, self.y_test = None, None
        self.class_names = None
        self.expected_bands = None

        self.pipe = self.build_pipeline()

    def build_pipeline(self):
        """Subclasses must return an sklearn Pipeline."""
        raise NotImplementedError

    def preprocessing_steps(self):
        """Reusable preprocessing for all NIR spectral classifiers."""
        return [
            ("savgol", SavGolTransformer(
                window_length=self.window_length,
                polyorder=self.polyorder,
                deriv=self.deriv,
            )),
            ("zscore", StandardScaler()),
        ]

    @staticmethod
    def _material_name_from_path(path):
        stem = Path(path).stem
        if stem.endswith("_timestamps"):
            raise ValueError(f"Do not pass timestamp files into training: {path}")
        return stem

    @staticmethod
    def _first_numeric_array_from_npz(npz, source_name):
        preferred = ("imnData", "data", "spectra", "X", "arr_0")
        for key in preferred:
            if key in npz.files:
                return npz[key]
        for key in npz.files:
            if not str(key).lower().endswith("timestamps"):
                return npz[key]
        raise ValueError(f"No spectral array found in NPZ file: {source_name}")

    @staticmethod
    def _numeric_excel_matrix(path, sheet_name=None):
        """Read an Excel sheet and return a dense numeric matrix.

        Rows with fewer than two numeric values are ignored. This allows files
        with one text/header column or header rows. Non-numeric cells inside a
        numeric row become NaN and columns that are completely NaN are removed.
        """
        try:
            from openpyxl import load_workbook
        except Exception as exc:
            raise ImportError("Excel loading requires openpyxl") from exc

        wb = load_workbook(path, data_only=True, read_only=True)
        if sheet_name is None:
            ws = wb[wb.sheetnames[0]]
        else:
            ws = wb[sheet_name]

        rows = []
        for row in ws.iter_rows(values_only=True):
            numeric = []
            n_numeric = 0
            for value in row:
                if isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(value, bool):
                    numeric.append(float(value))
                    n_numeric += 1
                else:
                    numeric.append(np.nan)
            if n_numeric >= 2:
                rows.append(numeric)

        wb.close()

        if not rows:
            raise ValueError(f"No numeric spectra found in Excel file: {path}")

        max_len = max(len(r) for r in rows)
        arr = np.full((len(rows), max_len), np.nan, dtype=np.float32)
        for i, row in enumerate(rows):
            arr[i, :len(row)] = row

        # Drop columns that are entirely non-numeric.
        valid_cols = ~np.all(np.isnan(arr), axis=0)
        arr = arr[:, valid_cols]

        # Drop rows that still contain NaN after removing non-numeric columns.
        # This is intentionally strict: each remaining row must be one complete spectrum.
        valid_rows = ~np.any(np.isnan(arr), axis=1)
        arr = arr[valid_rows]

        if arr.size == 0:
            raise ValueError(f"No complete numeric spectra found in Excel file: {path}")

        return arr.astype(np.float32, copy=False)

    def _normalise_2d_spectra_matrix(self, arr, source_name="array"):
        """Convert a 2-D numeric matrix to X=(n_spectra, bands).

        Preferred convention: rows are spectra and columns are bands.
        If the matrix appears transposed, e.g. (220, n_spectra), it is transposed.
        """
        arr = np.asarray(arr, dtype=np.float32)
        if arr.ndim != 2:
            raise ValueError(f"Expected 2D matrix for {source_name}, got shape={arr.shape}")

        if self.expected_bands is not None:
            if arr.shape[1] == self.expected_bands:
                return arr
            if arr.shape[0] == self.expected_bands:
                return arr.T
            raise ValueError(
                f"Band-count mismatch for {source_name}: shape={arr.shape}, "
                f"expected {self.expected_bands} bands."
            )

        # First file: infer orientation. Prefer known NIR band counts if present.
        for bands in self.COMMON_BAND_COUNTS:
            if arr.shape[1] == bands:
                return arr
            if arr.shape[0] == bands:
                return arr.T

        # Generic fallback: assume rows are spectra, columns are bands.
        return arr

    def _array_to_spectra_legacy_or_evk(self, arr, source_name="array"):
        """Convert spectral arrays to X=(n_spectra, bands).

        EVK SQALAR / new SenSoRTC:
            (width, bands, lines), e.g. (312, 220, nLines)

        Old SenSoRTC before transpose change:
            (lines, width, bands), e.g. (nLines, 312, 220)

        2-D matrices are handled by _normalise_2d_spectra_matrix().
        """
        arr = np.asarray(arr)

        if arr.ndim == 3:
            shape = arr.shape

            if self.expected_bands is not None:
                if shape[1] == self.expected_bands:  # EVK/new SenSoRTC
                    bands = shape[1]
                    return arr.transpose(0, 2, 1).reshape(-1, bands)
                if shape[2] == self.expected_bands:  # old SenSoRTC
                    bands = shape[2]
                    return arr.reshape(-1, bands)
                if shape[0] == self.expected_bands:
                    bands = shape[0]
                    moved = np.moveaxis(arr, 0, -1)
                    return moved.reshape(-1, bands)
                raise ValueError(
                    f"Band-count mismatch for {source_name}: shape={shape}, "
                    f"expected {self.expected_bands} bands."
                )

            # EVK/new SenSoRTC: (width, bands, lines)
            for bands in self.COMMON_BAND_COUNTS:
                if shape[1] == bands:
                    return arr.transpose(0, 2, 1).reshape(-1, bands)

            # Old SenSoRTC: (lines, width, bands)
            for bands in self.COMMON_BAND_COUNTS:
                if shape[2] == bands:
                    return arr.reshape(-1, bands)

            # Fallback: choose a plausible spectral axis. Prefer middle axis.
            candidate_axes = [i for i, s in enumerate(shape) if 16 <= s <= 4096]
            if not candidate_axes:
                raise ValueError(f"Cannot infer spectral axis for {source_name}: {shape}")

            spectral_axis = 1 if 1 in candidate_axes else candidate_axes[-1]
            bands = shape[spectral_axis]
            moved = np.moveaxis(arr, spectral_axis, -1)
            return moved.reshape(-1, bands)

        if arr.ndim == 2:
            return self._normalise_2d_spectra_matrix(arr, source_name=source_name)

        raise ValueError(f"Unsupported ndim for {source_name}: {arr.ndim}, shape={arr.shape}")

    def _filter_background(self, X, min_mean):
        X = np.asarray(X, dtype=np.float32)
        if min_mean is None:
            return X
        keep = X.mean(axis=1) >= float(min_mean)
        X = X[keep]
        if X.size == 0:
            raise ValueError(
                f"No spectra left after min_mean={min_mean}. "
                "Lower min_mean or check whether this file contains foreground material."
            )
        return X

    def _finish_loaded_X_y(self, X, label, min_mean, source_name):        

        if self.expected_bands is None:
            self.expected_bands = int(X.shape[1])
        elif X.shape[1] != self.expected_bands:
            raise ValueError(
                f"Band-count mismatch after loading {source_name}: "
                f"got {X.shape[1]}, expected {self.expected_bands}."
            )

        y = np.full(X.shape[0], label, dtype=np.uint8)
        return X, y

    def load_imnData_mat(self, path, label, min_mean=800):
        path = Path(path)
        mat = loadmat(path)

        if "imnData" in mat:
            arr = mat["imnData"]
        else:
            keys = [k for k in mat.keys() if not k.startswith("__")]
            if not keys:
                raise ValueError(f"No data arrays found in MAT file: {path}")
            arr = mat[keys[0]]

        X = self._array_to_spectra_legacy_or_evk(arr, source_name=str(path))
        X = self._filter_background(X, min_mean=min_mean)
        return self._finish_loaded_X_y(X, label, min_mean, source_name=str(path))

    def load_npy_spectral(self, path, label, min_mean=800):
        path = Path(path)
        if path.stem.endswith("_timestamps"):
            raise ValueError(f"This is a timestamp file, not spectral data: {path}")

        arr = np.load(path)
        X = self._array_to_spectra_legacy_or_evk(arr, source_name=str(path))
        X = self._filter_background(X, min_mean=min_mean)
        return self._finish_loaded_X_y(X, label, min_mean, source_name=str(path))

    def load_npz_spectral(self, path, label, min_mean=800):
        path = Path(path)
        with np.load(path) as npz:
            arr = self._first_numeric_array_from_npz(npz, source_name=str(path))
        X = self._array_to_spectra_legacy_or_evk(arr, source_name=str(path))
        X = self._filter_background(X, min_mean=min_mean)
        return self._finish_loaded_X_y(X, label, min_mean, source_name=str(path))

    def load_excel_spectral(self, path, label, min_mean=800, sheet_name=None):
        path = Path(path)
        arr = self._numeric_excel_matrix(path, sheet_name=sheet_name)
        X = self._normalise_2d_spectra_matrix(arr, source_name=str(path))
        return self._finish_loaded_X_y(X, label, min_mean, source_name=str(path))

    def load_spectral_file(self, path, label, min_mean=800):
        path = Path(path)
        suffix = path.suffix.lower()

        if suffix == ".mat":
            return self.load_imnData_mat(path, label, min_mean=min_mean)
        if suffix == ".npy":
            return self.load_npy_spectral(path, label, min_mean=min_mean)
        if suffix == ".npz":
            return self.load_npz_spectral(path, label, min_mean=min_mean)
        if suffix in (".xlsx", ".xlsm"):
            return self.load_excel_spectral(path, label, min_mean=min_mean)
        if suffix == ".xls":
            raise ValueError(".xls is not supported by openpyxl. Save as .xlsx or .xlsm.")

        raise ValueError(f"Unsupported file type: {path}")

    def load_data(self, paths, min_mean=800, test_size=0.2, random_state=None):
        if random_state is None:
            random_state = self.random_state

        self.expected_bands = None
        X_parts = []
        y_parts = []

        for class_idx, path in enumerate(paths, start=1):
            X_data, y_data = self.load_spectral_file(path, class_idx, min_mean=min_mean)
            print(f"Loaded {Path(path).name}: X={X_data.shape}, label={class_idx}")
            X_parts.append(X_data)
            y_parts.append(y_data)

        X = np.vstack(X_parts)
        y = np.concatenate(y_parts)

        self.X_train, self.X_test, self.y_train, self.y_test = train_test_split(
            X,
            y,
            test_size=test_size,
            stratify=y,
            random_state=random_state,
        )

    def train(self, paths, name=None, min_mean=800, test_size=0.2):
        if name is None:
            name = f"{self.__class__.__name__}.joblib"

        self.load_data(paths, min_mean=min_mean, test_size=test_size)
        self.pipe.fit(self.X_train, self.y_train)

        pred = self.pipe.predict(self.X_test)
        print(confusion_matrix(self.y_test, pred))

        material_names = [self._material_name_from_path(p) for p in paths]
        print(classification_report(
            self.y_test,
            pred,
            labels=list(range(1, len(paths) + 1)),
            target_names=material_names,
        ))

        bundle = {
            "pipeline": self.pipe,
            "class_names": ["Background"] + material_names,
            "class_labels": list(range(len(paths) + 1)),
            "kind": self.__class__.__name__,
            "format": "sklearn_pipeline_bundle_v1",
            "n_bands": self.expected_bands,
            "preprocessing": {
                "savgol_window_length": self.window_length,
                "savgol_polyorder": self.polyorder,
                "savgol_deriv": self.deriv,
                "zscore": "StandardScaler",
            },
        }

        joblib.dump(bundle, name)
        print(f"Saved: {name}")
        return self.pipe


class Shallow_NN(NIRPipelineBase):
    def __init__(
        self,
        window_length=15,
        polyorder=2,
        deriv=1,
        hidden_layer_sizes=(64, 32),
        random_state=42,
    ):
        self.hidden_layer_sizes = hidden_layer_sizes
        super().__init__(
            window_length=window_length,
            polyorder=polyorder,
            deriv=deriv,
            random_state=random_state,
        )

    def build_pipeline(self):
        return Pipeline(
            self.preprocessing_steps() + [
                ("mlp", MLPClassifier(
                    hidden_layer_sizes=self.hidden_layer_sizes,
                    activation="relu",
                    alpha=1e-4,
                    learning_rate_init=1e-3,
                    max_iter=500,
                    early_stopping=True,
                    random_state=self.random_state,
                )),
            ]
        )


class SVM_RBF(NIRPipelineBase):
    def __init__(
        self,
        window_length=15,
        polyorder=2,
        deriv=1,
        C=10.0,
        gamma="scale",
        class_weight="balanced",
        random_state=42,
    ):
        self.C = C
        self.gamma = gamma
        self.class_weight = class_weight
        super().__init__(
            window_length=window_length,
            polyorder=polyorder,
            deriv=deriv,
            random_state=random_state,
        )

    def build_pipeline(self):
        return Pipeline(
            self.preprocessing_steps() + [
                ("svm", SVC(
                    kernel="rbf",
                    C=self.C,
                    gamma=self.gamma,
                    class_weight=self.class_weight,
                )),
            ]
        )


class SVM_Linear(NIRPipelineBase):
    def __init__(
        self,
        window_length=15,
        polyorder=2,
        deriv=1,
        C=1.0,
        class_weight="balanced",
        random_state=42,
    ):
        self.C = C
        self.class_weight = class_weight
        super().__init__(
            window_length=window_length,
            polyorder=polyorder,
            deriv=deriv,
            random_state=random_state,
        )

    def build_pipeline(self):
        return Pipeline(
            self.preprocessing_steps() + [
                ("linear_svm", LinearSVC(
                    C=self.C,
                    class_weight=self.class_weight,
                    random_state=self.random_state,
                    max_iter=10000,
                )),
            ]
        )
