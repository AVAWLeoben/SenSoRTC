# -*- coding: utf-8 -*-
"""
Created on Fri Jun 12 15:38:46 2026

@author: GKoinig
"""

from scipy.io import loadmat
from pathlib import Path
import numpy as np
from openpyxl import Workbook


def load_imndata(path):
    mat = loadmat(path)

    if "imnData" in mat:
        return mat["imnData"]

    keys = [k for k in mat.keys() if not k.startswith("__")]
    if not keys:
        raise ValueError(f"No data array found in {path}")

    return mat[keys[0]]


# ------------------------------------------------------------------
# PE.mat -> PE.xlsx
# ------------------------------------------------------------------

arr = load_imndata("PE.mat")

# Convert (width, bands, lines) -> (n_spectra, bands)
X = arr.transpose(0, 2, 1).reshape(-1, arr.shape[1])
X = X[X.mean(axis=1) >= 800]   # remove background before Excel export
wb = Workbook()
ws = wb.active
ws.title = "PE"

for row in X:
    ws.append(row.tolist())

wb.save("PE.xlsx")

print("Saved PE.xlsx", X.shape)


# ------------------------------------------------------------------
# PP.mat -> PP.npy
# ------------------------------------------------------------------

arr = load_imndata("PP.mat")

# Save in EVK-compatible shape
np.save("PP.npy", arr)

print("Saved PP.npy", arr.shape)


# ------------------------------------------------------------------
# PET.mat -> PET.npz
# ------------------------------------------------------------------

arr = load_imndata("PET.mat")

# Save compressed
np.savez_compressed(
    "PET.npz",
    imnData=arr
)

print("Saved PET.npz", arr.shape)