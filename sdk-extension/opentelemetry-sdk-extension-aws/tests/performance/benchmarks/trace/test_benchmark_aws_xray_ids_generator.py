# Copyright The OpenTelemetry Authors
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
import os
import sys

_src_folder_path = os.path.dirname(__file__).split('/')[0:-4]
_aws_xray_file = os.path.join('/'.join(_src_folder_path), 'src')
sys.path.append(_aws_xray_file)

from opentelemetry.sdk.extension.aws.trace import AwsXRayIdGenerator

id_generator = AwsXRayIdGenerator()


def test_generate_xray_trace_id(benchmark):
    benchmark(id_generator.generate_trace_id)


def test_generate_xray_span_id(benchmark):
    benchmark(id_generator.generate_span_id)
