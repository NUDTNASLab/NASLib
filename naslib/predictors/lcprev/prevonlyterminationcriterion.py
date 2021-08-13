"""
This code is from https://github.com/akshayc11/Spearmint/tree/elc
which is authored by Akshay Chandrashekaran

It is an implementation of
Speeding up Hyper-parameter Optimization by Extrapolation of Learning Curves 
using Previous Builds, Chandrashekaran and Lane, 2017
"""

import sys

from abc import abstractmethod
import numpy as np
from pprint import pprint
from scipy.stats import norm

from naslib.predictors.lcprev.curvefunctions import all_models
from naslib.predictors.lcprev.gradient_descent import gradient_descent

IMPROVEMENT_PROB_THRESHOLD = 0.05
PREDICTIVE_STD_THRESHOLD = 0.005


class TerminationCriterion(object):
    """
    Base class for this form of early termination criterion.
    This uses multiple gradient descent starts to derive the
    parameters for matching previous runs to the current run
    with the constraint that the scaling factor is highly limited
    to be around 1 if the number of available samples for comparison
    is less, with the restriction being relaxed as more samples get
    available.
    """
    prob_x_greater_type = None
    xlim = None
    model = None
    has_fit =  False
    y_prev_list = None
    y_curr = None
    y_best = None
    a_b_losses = None
    min_y_prev = None
    recency_weighting = None
    monotonicity_condition = None
    def __init__(self, y_curr, xlim, prob_x_greater_type=None,
                 y_prev_list=[], n=100, predictive_std_threshold=PREDICTIVE_STD_THRESHOLD,
                 min_y_prev=1, recency_weighting=False, monotonicity_condition=True):
        """
        Constructor for the TerminationCriterion
        """
        self.prob_x_greater_type = prob_x_greater_type
        self.xlim = xlim
        self.y_prev_list = y_prev_list
        self.a_b_losses = []
        self.predictive_std_threshold=predictive_std_threshold
        self.min_y_prev = min_y_prev
        self.recency_weighting = recency_weighting
        self.monotonicity_condition = monotonicity_condition
        self.has_fit = self.fit(y_curr, n)
        
    def get_prediction(self, xlim=None, thin=None):
        return self.predict(xlim=xlim)
    
    def fit(self, y_curr, n):
        self.y_curr = y_curr
        if self.min_y_prev > len(self.y_prev_list):
            return False
        for y_idx in range(len(self.y_prev_list)):
            y_prev = self.y_prev_list[y_idx]
            a_b_losses = self.__get_gradients_and_losses(y_curr, y_prev, n=n)
            for a_b_loss in a_b_losses:
                self.a_b_losses.append(a_b_loss + (y_idx,))
        self.a_b_losses = sorted(self.a_b_losses, key=lambda x:x[2])[0:n]
        return True
    
    def predict(self, xlim=None, thin=None):
        r""" Predict the mean and standard deviation of the extrapolation using
        previous model information
        P(y_final | y_1:m; y_prevs)
        """
        if xlim is None:
            xlim = self.xlim
        
        y_caps = []
        if self.a_b_losses is None or len(self.a_b_losses) == 0:
            result = {'predictive_mean': 0.0,
                      'predictive_std': 1.0,
                      'found': False}
        else:
            for a_b_loss in self.a_b_losses:
                a, b, loss, y_idx = a_b_loss
                y_prev = self.y_prev_list[y_idx]
                y_cap = a*y_prev[xlim-1] + b
                if y_cap > 1.0 or y_cap < 0.0:
                    continue
                y_caps.append(y_cap)
            y_predict = np.mean(y_caps)
            y_std = np.std(y_caps)
            if y_predict >=0 and y_predict <= 1.0 and y_std >= 0.0:
                result = {"predictive_mean": y_predict,
                          "predictive_std": y_std,
                          "found": True}
            else:
                sys.stderr.write("y_predict is outside normal bounds: {} or incorrect std deviation: {}\n".format(y_predict, y_std))
                result = {"predictive_mean": y_predict,
                          "predictive_std": y_std,
                          "found": False}
        return result

    def posterior_prob_x_greater_than(self, y_best, xlim):
        '''
        posterior probability of predicted y at given time xlim is
        greater than a value y_best
        '''
        result = self.predict(xlim)
        if result['found'] == False:
            return 1.0
        else:
            predictive_mean = result['predictive_mean']
            predictive_std = result['predictive_std']
            return 1.0 - norm.cdf(y_best, loc=predictive_mean, scale=predictive_std)

    @abstractmethod
    def run(self, y_best, thin=None):
        """ The actual run function
        
        Abstract method to run the termination criterion check.
        
        Decorators:
            abstractmethod
        """
        pass

    def __get_gradients_and_losses(self, f_cs, f_ps, n=100):
        """
        This is a wrapper for the kind of gradient descent this
        termination criterion going to use. In this case, we will
        be using the default parameters.
        """
        min_len = min(len(f_cs), len(f_ps))
        f_c = f_cs[0:min_len]
        f_p = f_ps[0:min_len]
        f_c_max = max(f_cs)
        a_b_losses = []
        for i in range(int(2*n)):
            a_b_loss = gradient_descent(f_c, f_p, return_loss=True,
                                        recency_weighting=self.recency_weighting)
            if self.monotonicity_condition is True:
                a,b,loss = a_b_loss
                f_c_pred_fin = a * f_ps[-1] + b
                # Dont allow any combination that produces predictions that are
                # worse than best available result so far for current build
                if f_c_pred_fin < f_c_max:
                    # Discard this combination
                    continue

            a_b_losses.append(a_b_loss)
            if len(a_b_losses) == n:
                break
        return a_b_losses

class ConservativeTerminationCriterion(TerminationCriterion):
    def __init__(self, y_curr, xlim, prob_x_greater_type=None,
                 y_prev_list = [], n=100,
                 predictive_std_threshold=None,
                 min_y_prev=1,
                 recency_weighting=False,
                 monotonicity_condition=True):

        super(ConservativeTerminationCriterion, self).__init__(
            y_curr, xlim, prob_x_greater_type,
            y_prev_list=y_prev_list, n=n, min_y_prev=min_y_prev,
            recency_weighting=recency_weighting, monotonicity_condition=True, predictive_std_threshold=predictive_std_threshold)
    
    def run(self, y_best, threshold=IMPROVEMENT_PROB_THRESHOLD):
        """
        Run method for the conservative termination criterion
        """
        predictive_mean = None
        predictive_std = None
        found = False
        prob_gt_ybest_xlast = 0.0
        terminate = False
            
        # For NASLib, I removed a lot of print statements from the following code.
        # If the print statement was the only line, I replaced it with 'pass'
        if self.y_curr is None or len(self.y_curr)==0:
            pass
        else:
            y_c_best = np.max(self.y_curr)
            if y_c_best >= y_best:
                # let current build run to termination
                predictive_mean = y_c_best
                predictive_std = 0.0
                found = True
                prob_gt_ybest_xlast = 1.0
                terminate = False
            else:
                if self.has_fit == False:
                    pass
         
                else:
                    res = self.predict()
                    predictive_mean = res['predictive_mean']
                    predictive_std = res['predictive_std']
                    found = res['found']
                    prob_gt_ybest_xlast = self.posterior_prob_x_greater_than(y_best, self.xlim)
                    if found is False:
                        terminate = False
                    else:
                        if prob_gt_ybest_xlast < threshold:
                            # Probability of finding solution has fallen below a threshold
                            if self.predictive_std_threshold is None:
                                terminate = True
                            else:
                                if predictive_std < self.predictive_std_threshold:
                                    # The std deviation of the prediction has also fallen
                                    # below the threshold
                                    terminate = True
                                else:
                                    terminate = False
                        else:
                            terminate = False
        
        result = {'predictive_mean': predictive_mean,
                  'predictive_std': predictive_std,
                  'found': found,
                  'prob_gt_ybest_xlast':prob_gt_ybest_xlast,
                  'terminate': terminate}

        return result
