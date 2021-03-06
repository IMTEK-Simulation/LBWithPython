#!/usr/bin/env python3
"""
Copyright 2017-2018 Till Junge, Lars Pastewka, Andreas Greiner

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

try:
    import unittest
    import importlib
    import numpy as np
    from .PyLBTest import PyLBTestCase
except ImportError as err:
    import sys
    print(err)
    sys.exit(-1)

class ImportabilityChecks(PyLBTestCase):

    def import_module(self, module):
        return_code = -1
        try:
            importlib.import_module(module)
            return_code = 0
        except ImportError: pass
        return return_code

    def test_PyLB(self):
        self.assertEqual(self.import_module("PyLB"), 0)

if __name__ == '__main__':
    unittest.main()
