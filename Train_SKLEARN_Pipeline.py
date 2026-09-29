# -*- coding: utf-8 -*-
"""
Created on Fri Jun 12 12:42:04 2026

@author: GKoinig
"""

from SKLEARN_PIPELINES import Shallow_NN, SVM_RBF, SVM_Linear

paths = ["PE.mat", "PP.mat", "PET.mat"]

clf = Shallow_NN()
clf.train(paths, name="PE_PP_PET_SNN.joblib")

svm = SVM_RBF(C=10.0)
svm.train(paths, name="PE_PP_PET_SVM_RBF.joblib")

svm = SVM_Linear(C=10.0)
svm.train(paths, name="PE_PP_PET_SVM_Linear.joblib")

#%%
from SKLEARN_PIPELINES import Shallow_NN

paths = [
    "PE.xlsx",
    "PP.npy",
    "PET.npz",
]

clf = Shallow_NN()
clf.train(
    paths,
    name="PE_PP_PET_MIXED.joblib",
)