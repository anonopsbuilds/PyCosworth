#!/usr/bin/env python

# SerialIO - a serial datastream logger and display interface for
# Magneti Marelli ECU modules as used on the Ford Sierra/Escort Cosworth.
# Copyright (C) 2018  John Snowdon
# 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

# Standard libraries
import multiprocessing
import time
import timeit 
import sys
import os

# Settings file
from libs import settings
from libs.ControlData import ControlData

# Start a new logger
from libs.newlog import newlog
logger = newlog(__name__)

def setupDemoSensors():
	""" Generate demo data, from sensor minValue to maxValue, for a number of steps """
	
	logger.warn("Using DEMO data")
	logger.info("Generating sample demo data for sensors")
	demo_sensor = {}
	for sensor in settings.SENSORS:
		demo_sensor[sensor['sensorId']] = {
			'demo_data_idx' : 0,
			'demo_data' : []
		}
		demo_step_size = (sensor['maxValue'] * 1.0) / settings.DEMO_STEPS
		d_value = sensor['minValue']
		for d in range(0, settings.DEMO_STEPS):
			demo_sensor[sensor['sensorId']]['demo_data'].append(d_value)
			d_value += demo_step_size
		for d in range(0, settings.DEMO_STEPS):
			d_value = d_value - demo_step_size
			demo_sensor[sensor['sensorId']]['demo_data'].append(d_value)
		logger.debug("%s demo data %s" % (sensor['sensorId'], demo_sensor[sensor['sensorId']]['demo_data']))
	return demo_sensor

def SerialIO(transmitQueue, receiveQueue, controlQueue):
	""" Serial IO """
		
	proc_name = multiprocessing.current_process().name
	myButtonId = settings.BUTTON_DEST_SERIALIO
		
	# Initialise connection
	logger.info("Initialising serial IO")
	
	# Wait for initialisation
	time.sleep(5)
	
	logger.warn("Unable to initialise serial port")
	if settings.SERIALIO_DEMO:
		SERIALIO_DEMO = True
		demo_sensor = setupDemoSensors()
	else:
		SERIALIO_DEMO = False
	
	# Tell the data collector to use either real
	# data or just to send sample demo data instead
	connected = False
	
	# Find the sensor with the highest sample rate
	# we'll use this as our sample counter
	logger.info("Finding highest sample rate")
	highest_sample_rate = 99
	sample_counter_id = ""
	for sensor in settings.SENSORS:
		if sensor['refresh'] < highest_sample_rate:
			sample_counter_id = sensor['sensorId']
			highest_sample_rate = sensor['refresh']
	logger.info("Highest frequency sensor is: %s" % sample_counter_id)
	logger.info("Sample frequency is: %sHz" % (1 / highest_sample_rate))
	
	# Set up timers for all sensors
	logger.info("Reset timers")
	sensor_timer = {}
	for sensor in settings.SENSORS:
		sensor_timer[sensor['sensorId']] = timeit.default_timer()
	
	# Now we begin a continuous sample loop
	counter = 0
	demo_data_idx = 0
	
	####################################################
	#
	# This loop runs forever, or until the process is
	# signalled to exit
	#
	####################################################
	while True:
		
		sample_time = 0
		sample_start = timeit.default_timer()
		
		####################################################
		#
		# Listen for control messages
		#
		####################################################
		if controlQueue.empty() == False:
			cdata = controlQueue.get()
			if cdata.isMine(myButtonId):
				logger.info("Got a control message")
				cdata.show()
				# We only do two things:
				# short press - turn on/off demo mode
				# long press - reset serial connection
				
				# Reset serial connection
				if (cdata.button) and (cdata.duration == settings.BUTTON_LONG):
					# TO DO
					pass
				
				# Toggle demo mode
				if (cdata.button) and (cdata.duration == settings.BUTTON_SHORT):
					if SERIALIO_DEMO:
						logger.info("Stopping SerialIO DEMO mode")
						SERIALIO_DEMO = False
					else:
						logger.info("Starting SerialIO DEMO mode")
						SERIALIO_DEMO = True
						demo_sensor = setupDemoSensors()			
				
		
		####################################################
		#
		# If transmitQueue has any instructions, then
		# we've been asked to send a request to the ECU, 
		# so send it
		#
		####################################################
		if transmitQueue.empty() == False:
			logger.debug("Got a control code to send")
			txb = transmitQueue.get()
		else:
			txb = False
			
		# We have a control byte to send
		if txb:
			# Send the byte
			logger.info("Sending byte sequence [%s]" % txb)
			
			# Read the returned sequence
			logger.info("Reading response")
			
			# Put bytes in receiveQueue
			logger.info("Added to receiveQueue")
		
		####################################################
		#
		# Standard loop - do a read of sensors defined in
		# the settings file.
		#
		####################################################
		for sensor in settings.SENSORS:
			
			t = timeit.default_timer() - sensor_timer[sensor['sensorId']]
			
			# Has timer expired on sensor
			if (t >= sensor['refresh']):
				logger.debug("Waking sensorId:%s time:%s" % (sensor['sensorId'], t))
			
				if sensor['sensorId'] == sample_counter_id:
					# Increment sample counter
					counter += 1
					
					# How long did this sample run take?
					sample_end = timeit.default_timer()
					sample_time = sample_end - sample_start
					logger.debug("Sample loop took %4fms" % (sample_time * 1000))
			
				if SERIALIO_DEMO:
					# Send demo data
					demo_data_idx = demo_sensor[sensor['sensorId']]['demo_data_idx']
					rxb = demo_sensor[sensor['sensorId']]['demo_data'][demo_data_idx]
					
					logger.debug("Sending DEMO data[%s/%s] for sensorId:%s" % (demo_data_idx, rxb, sensor['sensorId']))
					
					receiveQueue.put((settings.TYPE_DATA, sensor['sensorId'], rxb, counter, sample_time))
					# Reset timer
					sensor_timer[sensor['sensorId']] = timeit.default_timer()
					
					if demo_sensor[sensor['sensorId']]['demo_data_idx'] < ((settings.DEMO_STEPS * 2)- 1):
						demo_sensor[sensor['sensorId']]['demo_data_idx'] += 1
					else:
						demo_sensor[sensor['sensorId']]['demo_data_idx'] = 0
					
				else:
					if connected:
						# Get data
						logger.debug("Reading sensorId:%s" % sensor['sensorId'])
						rxb = "0x0"
						receiveQueue.put((settings.TYPE_DATA, sensor['sensorId'], rxb, counter, sample_time))
						# Reset timer
						sensor_timer[sensor['sensorId']] = timeit.default_timer()
				
			else:
				pass
		
		# Sleep at the end of each round so that we don't
		# consume too many processor cycles. May need to experiment
		# with this value for different platforms.
		time.sleep(settings.SERIAL_SLEEP_TIME)