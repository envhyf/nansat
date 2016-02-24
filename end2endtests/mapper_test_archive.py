# ------------------------------------------------------------------------------
# Name:         mapper_test_archive.py
# Purpose:      To discover test data for the end2endtests
#
# Author:       Anton Korosov, Morten Wergeland Hansen, Asuka Yamakawa
# Modified:     Morten Wergeland Hansen, Aleksander Vines
#
# Created:      2014-06-18
# Last modified:2015-12-28 13:36
# Copyright:    (c) NERSC
# Licence:      This file is part of NANSAT. You can redistribute it or modify
#               under the terms of GNU General Public License, v.3
#               http://www.gnu.org/licenses/gpl-3.0.html
# ------------------------------------------------------------------------------
import os
import glob
import warnings

class DataForTestingMappers(object):
    def __init__(self):
        ''' Find test files and corresponding mapper names '''
        existingTestFiles = self.find_existing_files()
        self.mapperData = self.identify_mappers(existingTestFiles)

    def find_existing_files(self):
        ''' Find all files for testing inside MAPPER_TEST_DATA_DIR'''
        testFiles = []

        testDataEnv = os.getenv('MAPPER_TEST_DATA_DIR')
        if testDataEnv is None:
            warnings.warn('MAPPER_TEST_DATA_DIR is not defined')
        else:
            testDataDirs = testDataEnv.split(':')
            for testDataDir in testDataDirs:
                if os.path.isdir(testDataDir):
                    testFiles += glob.glob(os.path.join(testDataDir, '*', '*'))

        testFiles = [f for f in testFiles if self.readable(f)]

        return testFiles

    def identify_mappers(self, testFiles):
        ''' Get the name of the mapper from the sub-directory name '''

        return [{'fileName' : testFile,
                 'mapperName' : os.path.split(os.path.split(testFile)[0])[1]}
                for testFile in testFiles]

    def readable(self, testFile):
        ''' Test if file is readable at OS level '''
        if not os.path.exists(testFile):
            return False
        if not os.access(testFile, os.R_OK):
            return False
        if os.stat(testFile).st_size == 0:
            return False
        if os.path.isdir(testFile):
            return False

        return True

class DataForTestingOnlineMappers(object):
    mapperData = [
        {
            'fileName' : 'http://dap.ceda.ac.uk/data/neodc/esacci/sst/data/lt/Analysis/L4/v01.1/2010/05/01/20100501120000-ESACCI-L4_GHRSST-SSTdepth-OSTIA-GLOB_LT-v02.0-fv01.1.nc',
            'mapperName': 'sstcci_online'
        },{
        'fileName' : 'https://rsg.pml.ac.uk/thredds/dodsC/CCI_ALL-v2.0-MONTHLY',
        'mapperName' : 'occci_online',
        'date' : '2010-01-01'
        },{
        'fileName' : 'http://www.ifremer.fr/opendap/cerdap1/globcurrent/v2.0/global_025_deg/total_hs/2010/001/20100101000000-GLOBCURRENT-L4-CUReul_hs-ALT_SUM-v02.0-fv01.0.nc',
        'mapperName' : 'globcurrent_online'}
        ]
