#!/usr/bin/env python

# PyCosworth - a serial datastream logger and display interface for
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
import sys
import os

# Settings file
from libs import settings

# ECU data storage structure
from libs.EcuData import EcuData

# Any worker methods
from iomodules.SerialIO import SerialIO
from iomodules.ConsoleIO import ConsoleIO
from iomodules.MatrixIO import MatrixIO
from iomodules.GPIOButtonIO import GPIOButtonIO
from iomodules.GraphicsIO import GraphicsIO

# Start a new logger
from libs.newlog import newlog
if getattr(sys, 'frozen', False):
	__file__ = os.path.dirname(sys.executable)
logger = newlog(__file__)

def serialWorker(transmitQueue, receiveQueue, controlQueue):
	""" Runs the serial IO process to send and receive data from the ECU """
	SerialIO(transmitQueue, receiveQueue, controlQueue)
	
def consoleWorker(ecudata, controlQueue):
	""" Print sensor data to the terminal screen """
	ConsoleIO(ecudata, controlQueue)

def matrixLCDWorker(ecudata, controlQueue):
	""" Output sensor data to a Matrix Orbital text mode LCD """
	MatrixIO(ecudata, controlQueue)

def graphicsWorker(ecudata, controlQueue):
	""" Output sensor data to a Matrix Orbital text mode LCD """
	GraphicsIO(ecudata, controlQueue)

def gpioButtonWorker(actionQueue, stdin):
	""" Output sensor data to a Matrix Orbital text mode LCD """
	GPIOButtonIO(actionQueue, stdin)


#####################################################
#
# Add any user-defined worker functions here
# e.g.
#
# def myWorkerProcess(ecudata):
#	""" Do something else with the data """
#	myWorker(ecudata)
#
######################################################

if __name__ == '__main__':
	
	# Send and receive queues
	serialTransmitQueue = multiprocessing.Queue()
	serialReceiveQueue = multiprocessing.Queue()
	
	# A new ecu data structure
	dataManager = multiprocessing.Manager()
	ecuMatrixLCDDict = dataManager.dict(settings.MATRIX_CONFIG)
	ecuDataDict = dataManager.dict()
	ecuPrevDataDict = dataManager.dict()
	ecuCounter = multiprocessing.Value('d', 0)
	ecuSampleTime = multiprocessing.Value('d', 0.0)
	ecuErrors = multiprocessing.Array('i', range(settings.MAX_ERRORS))
	
	# Create a new ecudata class using the shared data structures from above
	ecuData = EcuData(ecuDataDict = ecuDataDict, 
		ecuPrevDataDict = ecuPrevDataDict,
		ecuCounter = ecuCounter, 
		ecuErrors = ecuErrors, 
		ecuSampleTime = ecuSampleTime, 
		ecuMatrixLCDDict = ecuMatrixLCDDict)
	for sensor in settings.SENSORS:
		ecuData.set_sensor(sensor = sensor)
			
	# A list of all worker processes
	workers = []

	# A list of all control queues
	messageQueues = []

	# Start the serial IO process
	serialControlQueue = multiprocessing.Queue()
	serial_p = multiprocessing.Process(target=serialWorker, args=(serialTransmitQueue, serialReceiveQueue, serialControlQueue))
	serial_p.start()
	workers.append(serial_p)
	messageQueues.append(serialControlQueue)
	
	###########################################################
	#
	# This block is where you add any workers that you also
	# want to have access to the sensor data returned from the ECU
	
	# Start the console IO process
	if settings.USE_CONSOLE:
		# The Console worker has a control queue that it listens for incoming control
		# messages on.
		consoleControlQueue = multiprocessing.Queue()
		console_p = multiprocessing.Process(target=consoleWorker, args=(ecuData, consoleControlQueue,))
		console_p.start()
		workers.append(console_p)
		messageQueues.append(matrixControlQueue)
	
	# Start the Matrix LCD process
	if settings.USE_MATRIX:
		# The MatrixLCD worker has a controle queue that it listens for incoming
		# control messages on.
		matrixControlQueue = multiprocessing.Queue()
		matrix_p = multiprocessing.Process(target=matrixLCDWorker, args=(ecuData, matrixControlQueue,))
		matrix_p.start()
		workers.append(matrix_p)
		messageQueues.append(matrixControlQueue)
    
    # Start the process to capture Raspberry Pi GPIO button presses
	if settings.USE_BUTTONS:
		# The GPIO/Button worker has an action queue that it PUTS message onto,
		# but it DOESNT need to access the ecuData data structure.
		gpioActionQueue = multiprocessing.Queue()
		my_stdin = sys.stdin.fileno()
		gpio_button_p = multiprocessing.Process(target=gpioButtonWorker, args=(gpioActionQueue, my_stdin))
		gpio_button_p.start()
		workers.append(gpio_button_p)
      
     # Start the OLED/SDL graphics process
	if settings.USE_GRAPHICS:
		# The OLED/SDL worker has a controle queue that it listens for incoming
		# control messages on.
		graphicsControlQueue = multiprocessing.Queue()
		matrix_p = multiprocessing.Process(target=graphicsWorker, args=(ecuData, graphicsControlQueue,))
		matrix_p.start()
		workers.append(matrix_p)
		messageQueues.append(graphicsControlQueue)
		
    # e.g.
    #
    # if settings.MY_WORKER:
    # 	# Add any more display processes here
    #	myControlQueue = multiprocessing.Queue()
    # 	myworker_p = multiprocessing.Process(target=myWorkerProcess, args=(ecuData, myControlQueue,))
    # 	myworker_p.start()
    # 	workers.append(myworker_p)
    #	messageQueues.append(myControlQueue)
    ############################################################
    
	# Start gathering data
	i = 0
	while True:
		
		if i == 10000:
			logger.info("Still running [main process]")
			i = 0
		# Get latest data  
		# If the receive queue has any data back...
		if serialReceiveQueue.empty() == False:
			logger.debug("Got some ECU data")
			d = serialReceiveQueue.get()
			# d0 = message_type
			# d1 = sensorId
			# d2 = sensor value
			# d3 = sample count
			# d4 = time taken for last data collection cycle
			
			# Check for type of the data
			if d[0] == settings.TYPE_ERROR:
				# We do special things for error messages
				logger.warn("ECU error message received")
			elif d[0] == settings.TYPE_DATA:
				# but for anything else we record it as a sensor value
				ecuData.data_previous[d[1]] = ecuData.data[d[1]]
				ecuData.data[d[1]] = d[2]
			else:
				logger.warn("Unknown message type from SerialIO process")
			
			# Always update the sample counter
			ecuData.counter.value = d[3]
			ecuData.timer.value = d[4]
		
		# Check for any GPIO button message
		if gpioActionQueue.empty() == False:
			logger.debug("Message in the control queue")
			gpioMessage = gpioActionQueue.get()
			# Distribute the messages to all processes
			# so that each process can decide what to do with it
			for q in messageQueues:
				q.put(gpioMessage)
		
		i += 1
		time.sleep(settings.MAIN_SLEEP_TIME)
    
	# Wait for the workers to finish
	serialTransmitQueue.close()
	serialTransmitQueue.join_thread()
	serialReceiveQueue.close()
	serialReceiveQueue.join_thread()
	
	for q in messageQueues:
		q.close()
		q.join_thread()
	
	for w in workers:
		w.join()