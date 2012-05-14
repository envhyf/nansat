# Name:     domain.py
# Purpose:  create domain based on either GDAL dataset or
#           proj4string and extentString
#
# Authors:      Asuka Yamakava, Anton Korosov, Knut-Frode Dagestad
#
# Created:     15.09.2011
# Copyright:   (c) NERSC 2012
# Licence:
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details:
# http://www.gnu.org/licenses/

import os.path
import re
import string

# test if methods with advanced libraries are available
try:
    useDomain2 = False
    import domain2
except ImportError:
    print '''Unable to import Basemap or Polygon or matplotlib.pyplot.
             No advanced operations'''
else:
    useDomain2 = True

import numpy as np
from xml.etree.ElementTree import ElementTree

try:
    from osgeo import gdal, osr
except ImportError:
    import gdal
    import osr

from nansat_tools import initial_bearing, add_logger

from vrt import VRT


class Error(Exception):
    '''Base class for exceptions in this module.'''
    pass


class OptionError(Error):
    '''Error for improper options (arguments) '''
    pass


class ProjectionError(Error):
    '''Cannot get the projection'''
    pass


class Domain():
    '''"Domain" is a grid with known dimentions and spatial reference'''

    def __init__(self, *args, **kwargs):
        '''Create Domain from given GDAL Dataset or textual options

        The main attribute of Domain is vrtDataset which is a GDAL
        Dataset of type MEM. It has such attributes as rasterXsize,
        rasterYsize, GeoTransform and GeoPorjection which fully describe
        dimentions and spatial reference of the grid. The MEM dataset is
        empty - it has no bands.
        If a GDAL dataset is given the Domain covers the same area and
        has the same resolution as the input Dataset.
        Textual options are srsString (proj4 syntax) and extentString
        (some of the gdalwarp otpions).

        Parameters: Domain(dataset) or Domain(srsString, extentString)
        ----------
        dataset: GDAL dataset, optional
        srsString : string, optional
            proj4 options [http://trac.osgeo.org/proj/]
            (e.g."+proj=utm +zone=25 +datum=WGS84 +no_defs")
            SPecifies spatial reference
        extentString : string, optional
            some gdalwarp options [http://www.gdal.org/gdalwarp.html] +
            additional options
            Specifies extent, resolution / size
            Available options: (("-te" or "-lle") and ("-tr" or "-ts"))
            (e.g. "-lle -10 30 55 60 -ts 1000 1000" or
            "-te 100 2000 300 10000 -tr 300 200")
            -tr resolutionx resolutiony
            -ts sizex sizey
            -te xmin ymin xmax ymax
            -lle lonmin latmin lonmax latmax
        name: string, optional
            Name to be added to the Domain object
        logLevel: int, optional, default=30
            level of logging

        Raises
        ------
        ProjectionError: occurs when Projection() is empty
            despite it is required for creating extentDic.
        OptionError: occures when the arguments are not proper.

        Modifies
        --------
        self.vrt.datasetset: dataset in memory
            dataset created based on the arguments

        See Also
        --------
        Nansat.reproject()
        [http://www.gdal.org/gdalwarp.html]
        [http://trac.osgeo.org/proj/]

        '''

        # test input options
        logLevel = 30
        if 'logLevel' in kwargs:
            logLevel = kwargs['logLevel']
        self.logger = add_logger('Nansat', logLevel=logLevel)

        self.name = ''
        if 'name' in kwargs:
            self.name = kwargs['name']

        # Domain(dataset=...) or Domain(dataset)
        gdalDataset = None
        if 'dataset' in kwargs:
            gdalDataset = kwargs['dataset']
        elif (len(args) > 0 and isinstance(args[0], gdal.Dataset)):
            gdalDataset = args[0]

        # Domain(srsString='...', extentString='...') or
        # Domain(srsString, extentString)
        srsString = None
        extentString = None
        if 'srsString' in kwargs and 'extentString' in kwargs:
            srsString = kwargs['srsString']
            extentString = kwargs['extentString']
        elif (len(args) > 1 and
              isinstance(args[0], str) and
              isinstance(args[1], str)):
            srsString = args[0]
            extentString = args[1]

        self.logger.debug('ds: %s' % str(gdalDataset))
        self.logger.debug('srs: %s' % srsString)
        self.logger.debug('ext: %s' % extentString)

        # test option when only dataset is given
        if gdalDataset is not None:
            self.vrt = VRT(gdalDataset=gdalDataset, logLevel=logLevel)

        # test option when proj4 and extent string are given
        elif (srsString is not None and extentString is not None):
            # if XML-file and domain name is given - read that file
            if os.path.isfile(srsString):
                srsString, extentString, self.name = self._from_xml(
                                                          srsString,
                                                          extentString)
            # import srs from srsString and get the projection
            srs = osr.SpatialReference()
            srs.ImportFromProj4(srsString)
            dstWKT = srs.ExportToWkt()
            if dstWKT == "":
                raise ProjectionError("srsString (%s) is wrong" % (
                                       srsString))

            # create full dictionary of parameters
            extentDic = self._create_extentDic(extentString)

            # convert -lle to -te
            if "lle" in extentDic.keys():
                extentDic = self._convert_extentDic(dstWKT, extentDic)

            # get size/extent from the created extet dictionary
            [geoTransform, rasterXSize,
                           rasterYSize] = self._get_geotransform(extentDic)
            # create VRT object with given geo-reference parameters
            self.vrt = VRT(srcGeoTransform=geoTransform, srcProjection=dstWKT,
                                           srcRasterXSize=rasterXSize,
                                           srcRasterYSize=rasterYSize,
                                           logLevel=logLevel)

        else:
            raise OptionError("'dataset' or 'srsString and extentString' "
                              "are required")

        self.logger.debug('vrt.dataset: %s' % str(self.vrt.dataset))

    def __repr__(self):
        '''Creates string with basic info about the Domain object

        Modifies
        --------
        Print size, projection and corner coordinates

        '''
        toPrettyWKT = osr.SpatialReference()
        toPrettyWKT.ImportFromWkt(self._get_projection(self.vrt.dataset))
        prettyWKT = toPrettyWKT.ExportToPrettyWkt(1)
        corners = self.get_corners()
        outStr = 'Domain:[%d x %d]\n' % (self.vrt.dataset.RasterXSize,
                                 self.vrt.dataset.RasterYSize)
        outStr += '-' * 40 + '\n'
        outStr += 'Projection:\n'
        outStr += prettyWKT + '\n'
        outStr += '-' * 40 + '\n'
        outStr += 'Corners (lon, lat):\n'
        outStr += '\t (%6.2f, %6.2f)  (%6.2f, %6.2f)\n' % (corners[0][0],
                corners[1][0], corners[0][2], corners[1][2])
        outStr += '\t (%6.2f, %6.2f)  (%6.2f, %6.2f)\n' % (corners[0][1],
                corners[1][1], corners[0][3], corners[1][3])
        return outStr

    def write_kml(self, xmlFileName=None, kmlFileName=None):
        '''Write KML file with domains

        Convert XML-file with domains into into KML-file for GoogleEart
        or
        Write KML-file with the current Domain

        Parameters
        ----------
        xmlFileName: string, optional
            Name of the XML-file to convert. If only this value is given
            - kmlFileName=xmlFileName+'.kml'

        kmlFileName: string, optional
            Name of the KML-file to generate from the current Domain

        '''
        # test input options
        if xmlFileName is not None and kmlFileName is None:
            # if only input XML-file is given - convert it to KML

            # open XML, get all domains
            xmlFile = file(xmlFileName, "rb")
            kmlFileName = xmlFileName + '.kml'
            xmlDomains = ElementTree(file=xmlFile).getroot()
            xmlFile.close()

            # convert domains in XML into list of domains
            domains = []
            for xmlDomain in list(xmlDomains):
                # append Domain object to domains list
                domainName = xmlDomain.attrib['name']
                domains.append(Domain(xmlFileName, domainName))

        elif xmlFileName is None and kmlFileName is not None:
            # if only output KML-file is given
            # then convert the current domain to KML
            domains = [self]

        else:
            # otherwise it is potentially error
            raise OptionError('Either xmlFileName(%s)\
             or kmlFileName(%s) are wrong' % (xmlFileName, kmlFileName))

        # open KML, write header
        kmlFile = file(kmlFileName, 'wt')
        kmlFile.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        kmlFile.write('<kml xmlns="http://www.opengis.net/kml/2.2" '
                      'xmlns:gx="http://www.google.com/kml/ext/2.2" '
                      'xmlns:kml="http://www.opengis.net/kml/2.2" '
                      'xmlns:atom="http://www.w3.org/2005/Atom">\n')
        kmlFile.write('<Document>\n')
        kmlFile.write('    <name>%s</name>\n' % kmlFileName)
        kmlFile.write('        <Folder><name>%s</name><open>1</open>\n'
                      % kmlFileName)

        # get border of each domain and add to KML
        for domain in list(domains):
            kmlEntry = domain._get_border_kml()
            kmlFile.write(kmlEntry)

        # write footer and close
        kmlFile.write('        </Folder></Document></kml>\n')
        kmlFile.close()

    def get_geolocation_grids(self):
        '''Get longitude and latitude grids representing the full data grid'''
        longitude = []
        latitude = []
        for i in range(self.vrt.dataset.RasterXSize):
            [lo, la] = self._transform_points(
                                [i] * self.vrt.dataset.RasterYSize,
                                range(self.vrt.dataset.RasterYSize))
            longitude.append(lo)
            latitude.append(la)
        return [longitude, latitude]

    def _convert_extentDic(self, dstWKT, extentDic):
        '''Convert -lle option (lat/lon) to -te (proper coordinate system)

        Source SRS from LAT/LON projection and target SRS from dstWKT.
        Create osr.CoordinateTransformation based on these SRSs and
        convert given values in degrees to the destination coordinate
        system given by WKT.
        Add key "te" and the converted values into the extentDic.

        Parameters
        ----------
        dstWKT: WKT
            destination WKT
        extentDic: dictionary
            dictionary with "lle" key

        Returns
        -------
        extentDic: dictionary
            input dictionary + "te" key and its values

        '''
        # Set destination SRS from dstWKT
        dstSRS = osr.SpatialReference()
        dstSRS.ImportFromWkt(dstWKT)

        coorTrans = osr.CoordinateTransformation(self._latlong_srs(), dstSRS)

        # convert lat/lon given by "lle" to the target coordinate system and
        # add key "te" and the converted values to extentDic
        x1, y1, z1 = coorTrans.TransformPoint(extentDic["lle"][0],
                                              extentDic["lle"][3])
        x2, y2, z2 = coorTrans.TransformPoint(extentDic["lle"][2],
                                              extentDic["lle"][3])
        x3, y3, z3 = coorTrans.TransformPoint(extentDic["lle"][2],
                                              extentDic["lle"][1])
        x4, y4, z4 = coorTrans.TransformPoint(extentDic["lle"][0],
                                              extentDic["lle"][1])

        minX = min([x1, x2, x3, x4])
        maxX = max([x1, x2, x3, x4])
        minY = min([y1, y2, y3, y4])
        maxY = max([y1, y2, y3, y4])

        extentDic["te"] = [minX, minY, maxX, maxY]

        return extentDic

    def _create_extentDic(self, extentString):
        '''Create a dictionary from extentString

        Check if extentString is proper.
            * "-te" and "-lle" take 4 numbers.
            * "-ts" and "-tr" take 2 numbers.
            * the combination should be ("-te" or "-lle") and ("-ts" or "-tr")
        If it is proper, create a dictionary
        Otherwise, raise the error.

        Parameters
        ----------
        extentString: string
            "-te xMin yMin xMax yMax",
            "-tr xResolution yResolution",
            "-ts width height",
            "-lle lonWest lonEast latNorth latSouth"

        Returns
        -------
        extentDic: dictionary
            has key ("te" or "lle") and ("tr" or "ts") and their values.

        Raises
        ------
        OptionError: occurs when the extentString is improper

        '''
        extentDic = {}

        # Find -re text
        str_tr = re.findall('-tr\s+[-+]?\d*[.\d*]*\s+[-+]?\d*[.\d*]*\s?',
                            extentString)
        if str_tr != []:
            # Check the number of -tr elements
            elm_str = str(str_tr[0].rstrip())
            elms_str = elm_str.split(None)
            if len(elms_str) != 3 or elms_str[2] == "-":
                raise OptionError("Domain._create_extentDic(): "
                                  "-tr is used as "
                                  "'-tr xResolution yResolution'")
            # Add the key and value to extentDic
            extentString = extentString.replace(str_tr[0], "")
            trElem = str(str_tr).split(None)
            trkey = trElem[0].translate(string.maketrans("", ""), "[]-'")
            if trkey != "":
                elements = []
                for i in range(2):
                    elements.append(float(trElem[i + 1].\
                                          translate(string.maketrans("", ""),
                                          "[]'")))
                extentDic[trkey] = elements

        # Find -ts text
        str_ts = re.findall('-ts\s+[-+]?\d*[.\d*]*\s+[-+]?\d*[.\d*]*\s?',
                            extentString)
        if str_ts != []:
            # Check the number of -ts elements
            elm_str = str(str_ts[0].rstrip())
            elms_str = elm_str.split(None)
            if len(elms_str) != 3 or elms_str[2] == "-":
                raise OptionError("Domain._create_extentDic(): "
                                  "-ts is used as '-ts width height'")
            # Add the key and value to extentDic
            extentString = extentString.replace(str_ts[0], "")
            tsElem = str(str_ts).split(None)
            tskey = tsElem[0].translate(string.maketrans("", ""), "[]-'")
            if tskey != "":
                elements = []
                for i in range(2):
                    elements.append(float(tsElem[i + 1].\
                                          translate(string.maketrans("", ""),
                                          "[]'")))
                extentDic[tskey] = elements

        # Find -te text
        str_te = re.findall('-te\s+[-+]?\d*[.\d*]*\s+[-+]?\d*[.\d*]*\s'
                            '+[-+]?\d*[.\d*]*\s+[-+]?\d*[.\d*]*\s?',
                            extentString)
        if str_te != []:
            # Check the number of -te elements
            elm_str = str(str_te[0].rstrip())
            elms_str = elm_str.split(None)
            if len(elms_str) != 5:
                raise OptionError("Domain._create_extentDic(): "
                                  "-te is used as '-te xMin yMin xMax yMax'")
            # Add the key and value to extentDic
            extentString = extentString.replace(str_te[0], "")
            teElem = str(str_te).split(None)
            tekey = teElem[0].translate(string.maketrans("", ""), "[]-'")
            if tekey != "":
                elements = []
                for i in range(4):
                    elements.append(float(teElem[i + 1].\
                                          translate(string.maketrans("", ""),
                                          "[]'")))
                extentDic[tekey] = elements

        # Find -lle text
        str_lle = re.findall('-lle\s+[-+]?\d*[.\d*]*\s+[-+]?\d*[.\d*]*\s'
                             '+[-+]?\d*[.\d*]*\s+[-+]?\d*[.\d*]*\s?',
                             extentString)
        if str_lle != []:
            # Check the number of -lle elements
            elm_str = str(str_lle[0].rstrip())
            elms_str = elm_str.split(None)
            if len(elms_str) != 5:
                raise OptionError("Domain._create_extentDic(): "
                                  "-lle is used as "
                                  "'-lle lonWest lonEast latNorth latSouth'")
            # Add the key and value to extentDic
            extentString = extentString.replace(str_lle[0], "")
            lleElem = str(str_lle).split(None)
            llekey = lleElem[0].translate(string.maketrans("", ""), "[]-'")
            if llekey != "":
                elements = []
                for i in range(4):
                    elements.append(float(lleElem[i + 1].\
                                          translate(string.maketrans("", ""),
                                          "[]'")))
                extentDic[llekey] = elements

        result = re.search("\S", extentString)

        # if there are unnecessary letters, give an error
        if result != None:
            raise OptionError("Domain._create_extentDic(): "
                              "extentString is not redable : ", extentString)

        # check if one of "-te" and "-lle" is given
        if ("lle" not in extentDic) and ("te" not in extentDic):
            raise OptionError("Domain._create_extentDic(): "
                              "'-lle' or '-te' is required.")
        elif ("lle" in extentDic) and ("te" in extentDic):
            raise OptionError("Domain._create_extentDic(): "
                              "'-lle' or '-te' should be chosen.")

        # check if one of "-ts" and "-tr" is given
        if ("ts" not in extentDic) and ("tr" not in extentDic):
            raise OptionError("Domain._create_extentDic(): "
                              "'-ts' or '-tr' is required.")
        elif ("ts" in extentDic) and ("tr" in extentDic):
            raise OptionError("Domain._create_extentDic(): "
                              "'-ts' or '-tr' should be chosen.")
        return extentDic

    def _from_xml(self, srsString, extentString):
        ''' Read strings from the given xml file

        Parameters
        ----------
        srsString: file name
            name of the input XML-file
        extentString: string
            name of the domain

        Returns
        -------
        srsString: string
            proj4 string of the destination
        extentString: string
            extent string of the destination
        name: string
            domain name

        Raises
        ------
        OptionError: occures when the given extentString is not
        in the XML-file

         '''
        # open file
        fd = file(srsString, "rb")
        # get root element
        domains = ElementTree(file=fd).getroot()
        fd.close()

        # iterate over domains to find the required one
        for domain in list(domains):
            # if the domain name is the same as the given one
            if domain.attrib['name'] == extentString:
                # get contents of the tags
                name = extentString[:]
                srsString = domain.find('srsString').text
                extentString = domain.find('extentString').text
                break
            if domain == list(domains)[-1]:
                raise OptionError("extentString is improper")

        return srsString, extentString, name

    def get_border(self, nPoints=10):
        '''Generate two vectors with values of lat/lon for the border of domain

        Parameters
        ----------
        nPoints: int, optional
            Number of points on each border

        Returns
        -------
        lonVec, latVec: lists
            vectors with lon/lat values for each point at the border

        '''
        # prepare vectors with pixels and lines for upper, left, lower
        # and right borders
        sizes = [self.vrt.dataset.RasterXSize, self.vrt.dataset.RasterYSize]

        rcVector1 = [[], []]
        rcVector2 = [[], []]
        # loop for pixels and lines
        for n in range(0, 2):
            step = max(1, sizes[n] / nPoints)
            rcVector1[n] = range(0, sizes[n], step)[0:nPoints]
            rcVector1[n].append(sizes[n])
            rcVector2[n] = rcVector1[n][:]
            rcVector2[n].reverse()

        # coumpund vectors of pixels (col) and lines (row)
        colVector = (rcVector1[0] + [sizes[0]] * len(rcVector1[1]) +
                    rcVector2[0] + [0] * len(rcVector1[1]))
        rowVector = ([0] * len(rcVector1[0]) + rcVector1[1] +
                    [sizes[1]] * len(rcVector1[0]) + rcVector2[1])

        return self._transform_points(colVector, rowVector)

    def _get_border_kml(self):
        '''Generate Placemark entry for KML

        Returns
        -------
        kmlEntry: String
            String with the Placemark entry

        '''
        domainLon, domainLat = self.get_border()

        # convert Border coordinates into KML-like string
        coordinates = ''
        for lon, lat in zip(domainLon, domainLat):
            coordinates += '%f,%f,0 ' % (lon, lat)

        kmlEntry = ''
        # write placemark: name, style, polygon, coordinates
        kmlEntry += '            <Placemark>\n'
        kmlEntry += '                <name>%s</name>\n' % self.name
        kmlEntry += '                <Style>\n'
        kmlEntry += '                    <LineStyle><color>ffffffff</color>'\
                    '</LineStyle>\n'
        kmlEntry += '                    <PolyStyle><fill>0</fill>'\
                    '</PolyStyle>\n'
        kmlEntry += '                </Style>\n'
        kmlEntry += '                <Polygon><tessellate>1</tessellate>'\
                    '<outerBoundaryIs><LinearRing><coordinates>\n'
        kmlEntry += coordinates + '\n'
        kmlEntry += '            </coordinates></LinearRing>'\
                    '</outerBoundaryIs></Polygon></Placemark>\n'

        return kmlEntry

    def _get_border_polygon(self):
        '''Creates string with WKT representation of the border polygon
        (this method is not used. Delete??)

        Returns
        -------
        WKTPolygon: string
            string with WKT representation of the border polygon

        '''
        lonList, latList = self.get_border()
        polyCont = ','.join(str(lon) + ' ' + str(lat) \
                   for lon, lat in zip(lonList, latList))
        wktPolygon = "PolygonFromText('POLYGON((%s))')" % polyCont
        return wktPolygon

    def get_corners(self):
        '''Get coordinates of corners of the Domain

        Returns
        -------
        lonVec, latVec: lists
            vectors with lon/lat values for each corner

        '''
        colVector = [0, 0, self.vrt.dataset.RasterXSize,
                     self.vrt.dataset.RasterXSize]
        rowVector = [0, self.vrt.dataset.RasterYSize, 0,
                     self.vrt.dataset.RasterYSize]
        return self._transform_points(colVector, rowVector)

    def _get_geotransform(self, extentDic):
        '''
        the new coordinates and raster size are calculated based on
        the given extentDic.

        Parameters
        ----------
        extentDic : dictionary
            includes "te" key and "ts" or "tr" key

        Raises
        ------
        OptionError: occurs when maxX - minX < 0 or maxY - minY < 0
        OptionError: occurs when the given resolution is larger than
                     width or height.

        Returns
        -------
        coordinate: list with 6 float
            GeoTransform

        rasterSize : list with two int
            rasterXSize and rasterYSize

        '''
        # recalculate GeoTransform based on extent option
        minX = extentDic["te"][0]
        minY = extentDic["te"][1]
        maxX = extentDic["te"][2]
        maxY = extentDic["te"][3]
        cornerX = minX
        cornerY = maxY
        width = maxX - minX
        height = maxY - minY
        if width <= 0 or height <= 0:
            raise OptionError("The extent is illegal. "
                              "'-te xMin yMin xMax yMax' ")

        if "tr" in extentDic.keys():
            resolutionX = extentDic["tr"][0]
            resolutionY = -(extentDic["tr"][1])
            if (width < resolutionX or height < resolutionY):
                raise OptionError("'-tr' is too large. "
                                  "width is " + width +
                                  "  height is " + height)
            rasterXSize = width / resolutionX
            rasterYSize = abs(height / resolutionY)
        else:
            rasterXSize = extentDic["ts"][0]
            rasterYSize = extentDic["ts"][1]
            resolutionX = width / rasterXSize
            resolutionY = -abs(height / rasterYSize)

        # create a list for GeoTransform
        coordinates = [cornerX, resolutionX, 0.0, cornerY, 0.0, resolutionY]

        return coordinates, int(rasterXSize), int(rasterYSize)

    def _get_projection(self, dataset):
        '''Get projection form dataset

        Get projection from GetProjection() or GetGCPProjection().
        If both are empty, raise error

        Return
        ------
        projection : projection or GCPprojection

        Raises
        ------
        ProjectionError: occurrs when the projection is empty.

        '''
        #get projection or GCPProjection
        projection = dataset.GetProjection()
        if projection == "":
            projection = dataset.GetGCPProjection()

        #test projection
        if projection == "":
            raise ProjectionError('Empty projection in input dataset!')

        return projection

    def _transform_points(self, colVector, rowVector):
        '''Transform given lists of X,Y coordinates into lat/lon

        Parameters
        ----------
        colVector: lists
            X and Y coordinates with any coordinate system

        Returns
        -------
        lonVector, latVector: lists
            X and Y coordinates in degree of lat/lon

        '''
        # get source SRS (either Projection or GCPProjection)
        srcWKT = self._get_projection(self.vrt.dataset)

        # prepare target WKT (pure lat/lon)
        dstWKT = self._latlong_srs().ExportToWkt()

        # create transformer
        transformer = gdal.Transformer(self.vrt.dataset, None,
                                       ['SRC_SRS=' + srcWKT,
                                       'DST_SRS=' + dstWKT])

        # use the transformer to convert pixel/line into lat/lon
        latVector = []
        lonVector = []
        for pixel, line in zip(colVector, rowVector):
            succ, point = transformer.TransformPoint(0, pixel, line)
            lonVector.append(point[0])
            latVector.append(point[1])

        return lonVector, latVector

    def _latlong_srs(self):
        '''Create SRS for latlong projectiom, WGS84

        Returns
        -------
            latlongSRS: osr.SpatialReference with projection for lat/long
        '''
        latlongSRS = osr.SpatialReference()
        latlongSRS.ImportFromProj4("+proj=latlong +ellps=WGS84 \
                                    +datum=WGS84 +no_defs")

        return latlongSRS

    def upwards_azimuth_direction(self):
        '''Caluculate and return upwards azimuth direction of domain.

        The upward azimuth direction will be the satellite flight
        direction (bearing) for unprojected satellite images.

        Returns
        -------
        bearing_center : float
            The upwards azimuth direction (bearing) in the center of
            the domain.
            NOTE: for longer domains especially at high latitudes
            the azimuth direction may vary a lot over the domain,
            and using the center angle will be a coarse approximation.
            This function should be updated to return a matrix
            of bearings interpolated to each pixel of the domain.
            This method should probably also get a better name.
        '''

        mid_x = self.vrt.dataset.RasterXSize / 2
        mid_y1 = self.vrt.dataset.RasterYSize / 2 * 0.4
        mid_y2 = self.vrt.dataset.RasterYSize / 2 * 0.6
        startlon, startlat = self._transform_points([mid_x], [mid_y1])
        endlon, endlat = self._transform_points([mid_x], [mid_y2])
        bearing_center = initial_bearing(
                    startlon[0], startlat[0], endlon[0], endlat[0])
        return bearing_center

    def shape(self):
        '''Return Numpy-like shape of Domain object (ySize, xSize)

        Returns
        -------
        shape: tuple of two INT
            Numpy-like shape of Domain object (ySize, xSize)
        '''
        return self.vrt.dataset.RasterYSize, self.vrt.dataset.RasterXSize

# import methods which use advanced libraries
if useDomain2:
    Domain.write_map = domain2.write_map
