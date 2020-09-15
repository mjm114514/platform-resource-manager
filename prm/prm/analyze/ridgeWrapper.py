# Copyright (C) 2018 Intel Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions
# and limitations under the License.
#
#
# SPDX-License-Identifier: Apache-2.0

""" This module implements ridge regression wrapper based on polynomial kernels """

import numpy as np
import sys
from sklearn.linear_model import Ridge
from sklearn.preprocessing import PolynomialFeatures
from sklearn.pipeline import make_pipeline
from scipy import special

epsilon = 0.000001


class RidgeWrapper(object):
    def __init__(self, normalize_error=False, print_log=0):
        self.normalize_error = normalize_error
        self.print_log = print_log

        self.baseline_evaluated = False

    def feed_data(self, x, y):
        self.x = x
        self.y = y

    def set_parameters(self, error, kernel):
        self.tmp_error = error
        self.tmp_kernel = kernel

    def set_best_parameters(self, error, kernel):
        self.best_error = error
        self.best_kernel = kernel

    def get_tmp_error(self, x):
        self.tmp_normalize_error = self.normalize_error
        return self.tmp_error

    def bootstrap_error(self, runs):
        training_size = int(len(self.x) / 3)
        if self.max_training_size < training_size:
            training_size = self.max_training_size
        total_error = 0
        for i in range(0, runs):
            np.random.seed(i)
            indices = np.random.permutation(len(self.x))
            tmp_x = self.x[indices]
            tmp_y = self.y[indices]
            x_train = tmp_x[0:training_size]
            y_train = tmp_y[0:training_size]
            ridge = RidgeWrapper.fit_regressor(x_train, y_train, self.best_error, self.best_kernel,
                                               self.tmp_normalize_error)
            x_train = tmp_x[(training_size + 1):(training_size * 2)]
            y_predict = ridge.predict(x_train)
            y_train = RidgeWrapper.floor((y_predict -
                                          tmp_y[(training_size + 1):(training_size * 2)]) ** 2)

            x_test = tmp_x[(training_size * 2 + 1):]
            y_predict = ridge.predict(x_test)
            y_test = RidgeWrapper.floor((y_predict -
                                         tmp_y[(training_size * 2 + 1):]) ** 2)

            _, error = RidgeWrapper.train_and_evaluate(x_train, y_train, x_test, y_test,
                                                       self.get_tmp_error(x_train),
                                                       self.tmp_kernel, self.tmp_normalize_error)
            if (self.print_log >= 4):
                print('  Round {0}: metric {1:.1f}%'.format(i, error))
            total_error += error
        return total_error / runs

    def bootstrap(self, training_size, runs):
        self.max_training_size = training_size
        total_error = 0
        for i in range(0, runs):
            np.random.seed(i)
            indices = np.random.permutation(len(self.x))
            tmp_x = self.x[indices]
            tmp_y = self.y[indices]
            x_train = tmp_x[0:training_size]
            y_train = tmp_y[0:training_size]
            x_test = tmp_x[training_size:]
            y_test = tmp_y[training_size:]
            _, error = RidgeWrapper.train_and_evaluate(x_train, y_train, x_test, y_test,
                                                       self.get_tmp_error(x_train),
                                                       self.tmp_kernel, self.tmp_normalize_error)
            if (self.print_log >= 4):
                print('  Round {0}: metric {1:.1f}%'.format(i, error))
            total_error += error
        return total_error / runs

    def cross_validate(self, cv_size):
        self.max_training_size = len(self.x) - cv_size
        total_error = 0
        np.random.seed(0)
        indices = np.random.permutation(len(self.x))
        tmp_x = self.x[indices]
        tmp_y = self.y[indices]
        runs = 0
        for i in range(0, len(self.y), cv_size):
            test_start = i
            test_end = i + cv_size
            if test_end > len(self.y):
                test_end = len(self.y)
            x_test = tmp_x[test_start:test_end]
            y_test = tmp_y[test_start:test_end]
            x_train = np.concatenate([tmp_x[0:test_start], tmp_x[test_end:]])
            y_train = np.concatenate([tmp_y[0:test_start], tmp_y[test_end:]])
            _, error = RidgeWrapper.train_and_evaluate(x_train, y_train, x_test, y_test,
                                                       self.get_tmp_error(x_train),
                                                       self.tmp_kernel, self.tmp_normalize_error)
            if (self.print_log >= 4):
                print('  Round {0}: metric {1:.1f}%'.format(runs, error))
            total_error += error
            runs += 1
        return total_error / runs

    def calc_p_value(self, x, y):
        y_predict, y_std = self.predict(x)
        span = (y - y_predict) / y_std
        return (1 - special.erf(-span / np.sqrt(2))) / 2

    def calc_datum_p_value(self, x, y):
        p_value = self.calc_p_value(np.array([x]), np.array([y]))
        return p_value[0]

    def predict(self, x):
        y_predict = self.regressor.predict(x)
        error_std = None

        error_std = np.array([self.error_stdev] * len(y_predict))
        return y_predict, error_std

    def predict_datum(self, x):
        y_predict, y_std = self.predict(np.array([x]))
        return y_predict[0], y_std[0]

    def get_log_density(self, x, y):
        y_predict, y_std = self.predict(x)
        span = (y - y_predict) / y_std
        return -np.log(y_std * np.sqrt(2 * np.pi)) - span * span / 2

    def get_datum_log_density(self, x, y):
        log_density = self.get_datum_log_density(np.array([x]), np.array([y]))
        return log_density[0]

    def get_error_stdev(self):
        return self.error_stdev

    def get_kernel(self):
        return self.regressor.get_kernel()

    def select_model(self, error_parameters, kernels, cv_size=1,
                     bootstrap_size=0, bootstrap_runs=10):
        min_error = sys.float_info.max
        for kernel_parameter in kernels:
            for error_parameter in error_parameters:
                self.set_parameters(error_parameter, kernel_parameter)
                error = 0
                if cv_size > 0:
                    error = self.cross_validate(cv_size)
                else:
                    error = self.bootstrap(bootstrap_size, bootstrap_runs)
                if min_error > error:
                    min_error = error
                    best_error_parameter = error_parameter
                    best_kernel = kernel_parameter
                if self.print_log >= 3:
                    print('Metric {0:.5f} w/ error paramter {1} & kernel {2}'.format(
                        error, error_parameter, kernel_parameter))
        if self.print_log >= 1:
            print('Best parameter with metric {:.1f}: {}, {}'.format(
                min_error, best_error_parameter, best_kernel))
        self.set_best_parameters(best_error_parameter, best_kernel)

    def retrain_model(self, bootstrap_size=0, seed=0):
        if bootstrap_size == 0:
            self.regressor = RidgeWrapper.fit_regressor(self.x, self.y, self.best_error,
                                                        self.best_kernel, self.normalize_error)
        else:
            np.random.seed(seed)
            indices = np.random.permutation(len(self.x))
            tmp_x = self.x[indices]
            tmp_y = self.y[indices]
            x_train = tmp_x[0:bootstrap_size]
            y_train = tmp_y[0:bootstrap_size]
            self.regressor = RidgeWrapper.fit_regressor(x_train, y_train, self.best_error,
                                                        self.best_kernel, self.normalize_error)

    def calc_constant_std(self):
        y_predict = self.regressor.predict(self.x)
        error = self.y - y_predict
        self.error_stdev = np.sqrt(np.mean(error * error))

    @staticmethod
    def floor(x):
        x[x < epsilon] = epsilon
        return x

    @staticmethod
    def evaluate_regressor(y_test, y_predict, metric_type=0):
        error = y_predict - y_test
        if metric_type == 0:
            return np.mean(error * error)
        if metric_type == 1:
            return np.mean(np.abs(error))

    @staticmethod
    def train_and_evaluate(x_train, y_train, x_test, y_test, error, degree,
                           normalize_error=False, metric_type=1):
        gp = RidgeWrapper.fit_regressor(x_train, y_train, error, degree, normalize_error)
        y_predict = gp.predict(x_test)
        metric = RidgeWrapper.evaluate_regressor(y_test, y_predict, metric_type=metric_type)
        return gp, metric

    @staticmethod
    def fit_regressor(x, y, error, degree, normalize_error=False):
        return NormalizedRidge.fit_regressor(x, y, error, degree, normalize_error=normalize_error)

    @staticmethod
    def build_model(x, y, error_parameters, kernels, cv_size=1,
                    bootstrap_size=0, bootstrap_runs=10, full_training=False,
                    print_log=0):
        if error_parameters is None:
            error_parameters = [0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10]
        if kernels is None:
            kernels = [1, 2, 3, 4]
        ridge = RidgeWrapper(print_log=print_log)
        ridge.feed_data(x, y)
        if print_log >= 1:
            print("Selecting model")
        ridge.select_model(error_parameters, kernels, cv_size, bootstrap_size,
                           bootstrap_runs)
        if cv_size > 0 or full_training:
            ridge.retrain_model()
        else:
            ridge.retrain_model(bootstrap_size, bootstrap_runs)
        ridge.calc_constant_std()
        return ridge


class NormalizedRidge(object):
    def __init__(self, x, y, error, degree,
                 normalize_error=False, scale_error=False):
        self.create_normalization(y)
        self.fit(x, y, error, degree,
                 normalize_error=normalize_error)

    def create_normalization(self, y):
        self.mean = y.mean()
        self.std = y.std()

    def normalize(self, y):
        return (y - self.mean) / self.std

    def denormalize(self, normalized_y):
        return normalized_y * self.std + self.mean

    def normalize_error(self, error):
        return error / self.std

    def denormalize_error(self, normalized_error):
        return normalized_error * self.std

    def fit(self, x, y, error, degree,
            normalize_error=False):
        if normalize_error:
            error = self.normalize_error(error)
        # using a pipeline to add non-linear features to a linear model
        self.ridge = make_pipeline(PolynomialFeatures(degree=degree, include_bias=True),
                                   Ridge(normalize=False, alpha=error * error,
                                         solver="svd")).fit(x, self.normalize(y))

    def predict(self, x):
        y_predict = self.ridge.predict(x)
        y_predict = self.denormalize(y_predict)
        return y_predict

    @staticmethod
    def fit_regressor(x, y, error, degree,
                      normalize_error=True, scale_error=False):
        return NormalizedRidge(x, y, error, degree,
                               normalize_error=normalize_error, scale_error=scale_error)
