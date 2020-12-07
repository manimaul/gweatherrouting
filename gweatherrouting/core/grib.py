# -*- coding: utf-8 -*-
# Copyright (C) 2017-2021 Davide Gessa
# Copyright (C) 2012 Riccardo Apolloni
'''
This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

For detail about GNU see <http://www.gnu.org/licenses/>.
'''

import requests
import logging
import tempfile
import random
import struct
import math
import json
import eccodes
import requests
from bs4 import BeautifulSoup

from . import utils
from .. import config

logger = logging.getLogger ('gweatherrouting')


class Grib:
	def __init__ (self):
		#self.parse (open ('/home/dakk/testgrib.grb', 'rb'))
		self.cache = {}

	def getDownloadList ():
		data = requests.get ('http://grib.virtual-loup-de-mer.org/').text
		soup = BeautifulSoup (data, 'html.parser')
		gribStore = []

		for row in soup.find ('table').find_all ('tr'):
			r = row.find_all ('td')

			if len (r) >= 4 and r[1].text.find ('.grb') != -1:
				gribStore.append ([r[1].text, 'NOAA', r[2].text, r[3].text, 'http://grib.virtual-loup-de-mer.org/' + r[1].find ('a', href=True)['href']])
		return gribStore


	# Get Wind data from cache if available (speed up the entire simulation)
	def _getWindDataCached (self, t, bounds):
		h = ('%f%f%f%f%f' % (t, bounds[0][0], bounds[0][1], bounds[1][0], bounds[1][1]))

		if h in self.cache:
			return self.cache [h]
		else:
			u = self.rindex [t]['u']
			v = self.rindex [t]['v']

			uu1, latuu, lonuu = [],[],[]
			vv1, latvv, lonvv = [],[],[]
			
			for x in u:
				if x['lat'] >= bounds[0][0] and x['lat'] <= bounds[1][0] and x['lon'] >= bounds[0][1] and x['lon'] <= bounds[1][1]: 
					uu1.append(x['value'])
					latuu.append(x['lat'])
					lonuu.append(x['lon'])

			for x in v:
				if x['lat'] >= bounds[0][0] and x['lat'] <= bounds[1][0] and x['lon'] >= bounds[0][1] and x['lon'] <= bounds[1][1]: 
					vv1.append(x['value'])
					latvv.append(x['lat'])
					lonvv.append(x['lon'])


			self.cache [h] = (uu1, vv1, latuu, lonuu)
			return self.cache [h]


	def getWind (self, t, bounds):
		t1 = int (int (round (t)) / 3) * 3
		t2 = int (int (round (t+6)) / 3) * 3

		if t2 == t1: t1 -= 3

		lon1 = min (bounds[0][1], bounds[1][1])
		lon2 = max (bounds[0][1], bounds[1][1])

		otherside = None

		if lon1 < 0.0 and lon2 < 0.0:
			lon1 = 180. + abs (lon1)
			lon2 = 180. + abs (lon2)
		elif lon1 < 0.0:
			otherside = (-180.0, lon1)
		elif lon2 < 0.0:
			otherside = (-180.0, lon2)

		bounds = [(bounds[0][0], min (lon1, lon2)), (bounds[1][0], max (lon1, lon2))]
		(uu1, vv1, latuu, lonuu) = self._getWindDataCached (t1, bounds)
		(uu2, vv2, latuu2, lonuu2) = self._getWindDataCached (t2, bounds)

		if otherside:
			bounds = [(bounds[0][0], min (otherside[0], otherside[1])), (bounds[1][0], max (otherside[0], otherside[1]))]
			dataotherside = self.getWind (t, bounds)
		else:
			dataotherside = []

		data = []		
		for i in range (0, len ([uu1])):
			data2 = []
			for j in range (0, len ([uu1][i])):
				lon = [lonuu][i][j]
				lat = [latuu][i][j]

				if lon > 180.0:
					lon = -180. + (lon - 180.)

				#if utils.pointInCountry (lat, lon):
				#	continue

				uu = [uu1][i][j] + ([uu2][i][j] - [uu1][i][j]) * (t - t1) * 1.0 / (t2 - t1)
				vv = [vv1][i][j] + ([vv2][i][j] - [vv1][i][j]) * (t - t1) * 1.0 / (t2 - t1)
				
				tws=0
				twd=0
				tws=(uu**2+vv**2)/2.
				twd=math.atan2(uu,vv)+math.pi
				twd=utils.reduce360(twd)

				data2.append ((math.degrees(twd), tws, (lat, lon)))
			data.append (data2)

		return data + dataotherside



	# Get wind direction and speed in a point, used by simulator
	def getWindAt (self, t, lat, lon):	
		bounds = [(math.floor (lat * 2) / 2., math.floor (lon * 2) / 2.), (math.ceil (lat * 2) / 2., math.ceil (lon * 2) / 2.)]
		data = self.getWind (t, bounds)

		if len (data[0]) == 0:
			print (lat,lon)
		wind = (data[0][0][0], data[0][0][1])
		return wind



	def parse (self, path):
		self.grbs = eccodes.GribFile (path) 

		self.rindex = {}
		timeIndex = 0
			
		for r in self.grbs:
			# timeIndex = str(r['dataDate'])+str(r['dataTime'])
			if r['name'] == '10 metre U wind component':
				self.rindex [timeIndex] = { 'u': eccodes.codes_grib_get_data(r.gid) }
			elif r['name'] == '10 metre V wind component':
				self.rindex [timeIndex]['v'] = eccodes.codes_grib_get_data(r.gid)
				timeIndex += 1
			

		

	def download (self, uri, percentageCallback, callback):
		logger.info ('starting download of %s' % uri)

		response = requests.get(uri, stream=True)
		total_length = response.headers.get('content-length')
		last_signal_percent = -1
		f = open ('/home/dakk/testgrib.grb', 'wb')

		if total_length is None:
			pass
		else:
			dl = 0
			total_length = int(total_length)
			for data in response.iter_content (chunk_size=4096):
				dl += len (data)
				f.write (data)
				done = int (100 * dl / total_length)
				
				if last_signal_percent != done:
					percentageCallback (done)  
					last_signal_percent = done
		
		f.close ()
		logger.info ('download completed %s' % uri)

		self.parse ('/home/dakk/testgrib.grb')
		callback (True)