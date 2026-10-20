"""Hybrid fraud model: CatBoost (fraud-sensitive) blended with Random Forest (precision/accuracy).
Both members are the already-trained, validation-calibrated pipelines; the blend exposes predict_proba
so scoring, thresholds, explanations and monitoring in the app work unchanged."""
import numpy as np

class HybridModel:
    def __init__(self,catboost,forest,weight_catboost=.5):
        self.catboost=catboost;self.forest=forest;self.weight=float(weight_catboost);self.classes_=np.array([0,1])
    def predict_proba(self,X):
        p=self.weight*self.catboost.predict_proba(X)[:,1]+(1-self.weight)*self.forest.predict_proba(X)[:,1]
        return np.column_stack([1-p,p])
