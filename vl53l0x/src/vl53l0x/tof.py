# Copyright (c) 2018, Sebastien Gemme
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this
# list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright notice,
# this list of conditions and the following disclaimer in the documentation
# and/or other materials provided with the distribution.
#
# 3. Neither the name of the copyright holder nor the names of its contributors
# may be used to endorse or promote products derived from this software without
# specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.


'''
Created on Feb 17, 2018

@author: seb
'''
from __future__ import division

import rospy
from vl53l0x_msgs.srv._StartRanging import StartRanging, StartRangingResponse, \
    StartRangingRequest
from std_srvs.srv._Trigger import Trigger, TriggerResponse
import VL53L0X
from sensor_msgs.msg._Range import Range
import math
import threading
import RPi.GPIO as GPIO
import time

ADDRESS_PARAM = "~address"
XSHUT_GPIO_PARAM = "~xshut_gpio"


class VL53L0x(object):

    def __init__(self):
        '''
        Constructor
        '''
        rospy.init_node("vl53l0x")
        
        self.__lock = threading.Lock()
        
        self.__initSensor()        
        
        # Advertise services
        self.__initServices()
        
        self.__initTopics()
        
        self.__isRanging = False
        
        self.__rangingThread = None            
        
        # Check if we want to start ranging automatically
        if rospy.get_param("~autostart", False):
            # If mode is not specified, start in VL53L0X_BETTER_ACCURACY_MODE by default.
            mode = rospy.get_param("~mode", StartRangingRequest.VL53L0X_BETTER_ACCURACY_MODE)
            rospy.loginfo("Autostarting ranging in mode " + repr(mode))
            req = StartRangingRequest(mode)
            res = self.__startRanging(req)
            
            if not res.success:
                rospy.logerr("Failed to automatically start ranging: " + res.message)
    
    def __initSensor(self):
        if not rospy.has_param(ADDRESS_PARAM):  # Just using the standard address (0x29)
            self.__tof = VL53L0X.VL53L0X()
        else:  # Expecting to have a gpio
            assert(isinstance(rospy.get_param(ADDRESS_PARAM),int))
            
            if not rospy.has_param(XSHUT_GPIO_PARAM):
                raise rospy.ROSException("Must specify the GPIO connected to the xshut down pin (parameter " + XSHUT_GPIO_PARAM + ")")
            else:
                rospy.loginfo("Configuring address to " + repr(hex(rospy.get_param(ADDRESS_PARAM))))
                assert(isinstance(rospy.get_param(XSHUT_GPIO_PARAM),int))            
                xshutGPIO = rospy.get_param(XSHUT_GPIO_PARAM)

                GPIO.setwarnings(False)
                # Setup GPIO for shutdown pins on each VL53L0X
                GPIO.setmode(GPIO.BCM)
                GPIO.setup(xshutGPIO, GPIO.OUT)
                # Set all shutdown pins low to turn off each VL53L0X
                GPIO.output(xshutGPIO, GPIO.LOW)
                # Make sure the sensor resets
                time.sleep(0.5)
                self.__tof = VL53L0X.VL53L0X(rospy.get_param(ADDRESS_PARAM))
                
                # Turn on the sensor
                GPIO.output(xshutGPIO, GPIO.HIGH)
                time.sleep(0.5)
    
    def __initServices(self):
        self.__startRangingSrv = rospy.Service("~start_ranging", StartRanging, self.__startRanging)
        self.__stopRangingSrv = rospy.Service("~stop_ranging", Trigger, self.__stopRanging)
        
    def __initTopics(self):
        self.__rangePub = rospy.Publisher("~range", Range, queue_size=10)
        
    def __startRanging(self, req):
        
        res = StartRangingResponse()
        
        if not self.__isRanging:
            with self.__lock:
                self.__tof.start_ranging(req.mode)        
                self.__isRanging = True
                res.success = True
            
                # Get the timing information in order to determine how fast
                # we need to poll the tof, timing is in micro seconds
                timing = self.__tof.get_timing()
                if (timing < 20000):
                    timing = 20000
            
                period = rospy.Duration(timing / 1e+6)
                rospy.loginfo("Polling at " + repr(period.nsecs / 1e+9) + "s")
            
                self.__rangingThread = rospy.Timer(period, self.__readRange)
            
        else:
            res.success = False
            res.message = "Already Ranging"
        
        return res;
    
    def __readRange(self, evt):
        
        reading = Range()
        
        reading.header.frame_id = rospy.get_param("~frame_id", "range_finder")
        reading.header.stamp = rospy.Time.now()
        
        reading.radiation_type = Range.INFRARED
        reading.field_of_view = rospy.get_param("~fov", math.radians(25.0))
        
        reading.min_range = rospy.get_param("~min_range", 0.005)
        reading.max_range = rospy.get_param("~max_range", 2.0)
       
        with self.__lock: 
            reading.range = self.__tof.get_distance() / 1000.0
        
        self.__rangePub.publish(reading)
        
    def __stopRanging(self, req):
        
        res = TriggerResponse()
        
        if self.__isRanging:
            with self.__lock:
                self.__tof.stop_ranging()
            res.success = True
            self.__isRanging = False
            self.__rangingThread.shutdown()
        else:
            res.success = False
            res.message = "Not Ranging"
        
        return res
