#   Copyright (c) 2021 PaddlePaddle Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import unittest
import numpy as np
import paddle
from paddle import nn
from paddle.nn import functional as F

np.random.seed(10)
paddle.seed(10)


class TestNNAdaptiveLogSoftmaxWithLossAPI(unittest.TestCase):
    def test_adaptive_log_softmax(self):
        # args validation
        with self.assertRaises(ValueError):
            _ = nn.AdaptiveLogSoftmaxWithLoss(16, 20, [5, 15, 15], div_value=2.)

        with self.assertRaises(ValueError):
            _ = nn.AdaptiveLogSoftmaxWithLoss(16, 20, [5, 15, 10], div_value=2.)

        with self.assertRaises(ValueError):
            _ = nn.AdaptiveLogSoftmaxWithLoss(16, 20, [5, 10, 25], div_value=2.)

        with self.assertRaisesRegex(ValueError,
                                    "cutoffs should be a sequence of unique,"):
            _ = nn.AdaptiveLogSoftmaxWithLoss(16, 20, [5, 10, 20], div_value=2.)

        # not raise
        _ = nn.AdaptiveLogSoftmaxWithLoss(16, 20, [5, 10, 19], div_value=2.)

        # input shapes
        with self.assertRaisesRegex(
                RuntimeError, r"Input and target should have the same size"):
            asfm = nn.AdaptiveLogSoftmaxWithLoss(
                16, 20, [5, 10, 15], div_value=2.)
            x = paddle.randn((2, 16))
            y = paddle.to_tensor([0, 5, 10])
            asfm(x, y)

        # out-of-bound targets
        with self.assertRaisesRegex(RuntimeError,
                                    r"Target values should be in"):
            asfm = nn.AdaptiveLogSoftmaxWithLoss(
                16, 20, [5, 10, 15], div_value=2.)
            x = paddle.randn((128, 16))
            y = paddle.randint(low=21, high=200, shape=[128])
            asfm(x, y)

        # cluster sizes
        asfm = nn.AdaptiveLogSoftmaxWithLoss(16, 20, [5, 10, 15], div_value=2.)
        x = paddle.randn((128, 16))
        y = paddle.randint(low=0, high=20, shape=[128])
        # x = paddle.randn((3, 16))
        # y = paddle.to_tensor((0, 17))

        self.assertEqual(
            asfm.head.weight.shape,
            [16, 5 + 3])  # 5 targets in head, 3 clusters, dimensionality 16
        self.assertEqual(asfm.tail[0][1].weight.shape,
                         [8, 5])  # 5 targets in this cluster, dimensionality 8
        self.assertEqual(asfm.tail[1][1].weight.shape, [4, 5])
        self.assertEqual(asfm.tail[2][1].weight.shape, [2, 5])

        self.assertEqual(asfm(x, y).output.shape, [128])

        # log_probs actually returns log_proba
        asfm = nn.AdaptiveLogSoftmaxWithLoss(8, 4, [2], div_value=2.)
        x = paddle.randn((4, 8))
        logprob_out = asfm.log_prob(x)
        np.testing.assert_array_almost_equal(
            paddle.exp(logprob_out).sum(1), paddle.ones([4]))
        # if_equal=(paddle.abs(paddle.exp(logprob_out).sum(1)-paddle.ones([4]))<paddle.ones([4])*1e-5).numpy().tolist()
        # true_var=[True]*4

        # self.assertEqual(if_equal,true_var)

        # forward returns the same thing as log_probs
        for v in [0, 1, 2, 3]:
            y = paddle.full((4, ), v, dtype='int64')
            out, loss = asfm(x, y)
            # if_equal=(paddle.abs(out-logprob_out.gather(y.unsqueeze(1),1).squeeze())<paddle.ones([4])*1e-5).numpy().tolist()
            # true_var=[True]*4
            np.testing.assert_array_almost_equal(
                out,
                logprob_out.gather(y.unsqueeze(1), 1).slice([1], [0],
                                                            [1]).squeeze())
            # self.assertEqual(out, logprob_out.gather(y.unsqueeze(1),1).squeeze())
            # self.assertEqual(if_equal,true_var)
            np.testing.assert_array_almost_equal(loss,
                                                 F.nll_loss(logprob_out, y))
            # self.assertEqual(loss, F.nll_loss(logprob_out, y))

        # predict
        x = paddle.abs(paddle.randn((64, 8)))

        # argmax in shortlist
        asfm = nn.AdaptiveLogSoftmaxWithLoss(
            8, 10, [4, 8], div_value=2., head_bias=True)
        asfm.head.weight.detach().abs()
        asfm.head.bias.detach().abs()
        asfm.head.weight.detach()[asfm.shortlist_size:, :] *= 0.

        out = asfm.predict(x)
        np.testing.assert_array_almost_equal(
            out, asfm.log_prob(x).argmax(axis=1))

        # argmax outside of shortlist
        asfm = nn.AdaptiveLogSoftmaxWithLoss(
            8, 10, [4, 8], div_value=2., head_bias=True)
        asfm.head.weight.detach().abs()
        asfm.head.bias.detach().abs()
        asfm.head.weight.detach()[:asfm.shortlist_size, :] *= 0.

        out = asfm.predict(x)
        np.testing.assert_array_almost_equal(
            out, asfm.log_prob(x).argmax(axis=1))

        # half of the argmax in shortlist, half in clusters
        asfm = nn.AdaptiveLogSoftmaxWithLoss(
            8, 10, [4, 8], div_value=2., head_bias=True)
        asfm.head.weight.detach().abs()
        asfm.head.bias.detach().abs()

        x[:32, :asfm.shortlist_size] *= 0.
        x[32:, asfm.shortlist_size:] *= 0.

        asfm.head.weight.detach()[:asfm.shortlist_size,
                                  asfm.shortlist_size:] *= 0.
        asfm.head.weight.detach()[asfm.shortlist_size:, :
                                  asfm.shortlist_size] *= 0.

        out = asfm.predict(x)
        np.testing.assert_array_almost_equal(
            out, asfm.log_prob(x).argmax(axis=1))


if __name__ == "__main__":
    unittest.main()
