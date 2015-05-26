# door.py
# IoT Video Series Airlock Door Controller
# Shawn Hymel @ SparkFun Electronics
# May 20, 2015
# https://github.com/sparkfun/IoT_Airlock
#
# Runs on an Edison to receive input from an Arduino, which controls the
# security sensors. The Edison posts photos of uncleared individuals to Twitter
# and opens doors for cleared individuals.
# This code is beerware; if you see me (or any other SparkFun 
# employee) at the local, and you've found our code helpful, please
# buy us a round!
# 
# To install bluepy:
# http://shawnhymel.com/665/using-python-and-ble-to-receive-data-from-the-rfduino/
# Copy the bluepy folder to IoT_Airlock/Edison
#
# Distributed as-is; no warranty is given.

################################################################################
# Global Constants
################################################################################

from twython import Twython, TwythonStreamer, TwythonError
from bluepy.btle import UUID, Peripheral
import pygame.camera
import pygame.image
import threading
import signal
import sys
import mraa
import time
import struct

# Parameters
DEBUG = 1
STOP_STREAM_ON_FAIL = True
IMG_NAME = 'intruder.jpeg'
ONLINE_MSG = 'Good morning! I am awake and ready to protect the door.'
SUCCESS_MSG = 'Welcome home, '
FAILURE_MSG = 'Someone is at the door.'
NAMES = ['@ShawnHymel'] #, '@NorthAllenPoole', '@Sarah_Al_Mutlaq']
HANDLE = '@SFE_Fellowship'
INNER_ADDR = 'F9:D8:C2:B9:77:E9'
OUTER_ADDR = 'D4:2C:92:60:C2:D5'

# GPIO pins
SUCCESS_PIN = 31    # GP44
FAILURE_PIN = 45    # GP45
STATUS_PIN_0 = 32   # GP46
STATUS_PIN_1 = 46   # GP47
REED_OUTER_PIN = 33 # GP48
DOORBELL_PIN = 47   # GP49
REED_INNER_PIN = 14 # GP13
DENY_PIN = 36       # GP14
APPROVE_PIN = 48     # GP15

# Bluetooth message constants
MSG_LOCK = 0x10
MSG_UNLOCK = 0x11
MSG_STATE_REQ = 0x12

# Define read and write UUIDs
READ_UUID = UUID(0x2221)
WRITE_UUID = UUID(0x2222)

# Twitter credentials
APP_KEY = 'sppWdEK9E3RVjo70zOKr6p7y1'
APP_SECRET = 'cRUKs3no6JSYubr6QqalgehhYfqIJYkNcvBLQMUIxfoUx9eQjB'
OAUTH_TOKEN = '3220604167-IvvyfABekUBIhP1twLlgko4ufvwqG8HTYAg5m3F'
OAUTH_TOKEN_SECRET = 'BoKwdbHc0tO4dQ15UZfutBrkmOkwL6J9DABA3YiBlsAH1'

################################################################################
# Global Variables
################################################################################

g_mainloop = False

################################################################################
# Classes
################################################################################

# Streamer class. Use this to look for commands on Twitter.
class ListenStreamer(TwythonStreamer):

    # [Constructor] Inherits a Twython streamer
    def __init__(self, parent, app_key, app_secret, oauth_token, 
                    oauth_token_secret, timeout=300, retry_count=None, 
                    retry_in=10, client_args=None, handlers=None, 
                    chunk_size=1):
        TwythonStreamer.__init__(self, app_key, app_secret, oauth_token, 
                    oauth_token_secret, timeout=300, retry_count=None, 
                    retry_in=10, client_args=None, handlers=None, 
                    chunk_size=1)
        self.parent = parent

    # Callback from streamer when tweet matches the search term(s)
    def on_success(self, data):
        if 'text' in data:
            print data['text'].encode('utf-8')
                
    # Callback from streamer if error occurs
    def on_error(self, status_code, data):
        print status_code, data
        if STOP_STREAM_ON_FAIL:
            self.stop()
        
    # Called from main thread to stop the streamer
    def stop(self):
        self.disconnect()

# TweetFeed class sets up the streamer and provides access to the tweets
class TweetFeed:

    # [Constructor] Set up streamer thread
    def __init__(self, twitter_auth):
    
        # Extract authentication tokens
        app_key = twitter_auth['app_key']
        app_secret = twitter_auth['app_secret']
        oauth_token = twitter_auth['oauth_token']
        oauth_token_secret = twitter_auth['oauth_token_secret']
        self.auth_args = (  app_key, 
                            app_secret, 
                            oauth_token, 
                            oauth_token_secret)
                            
        # Setup Twitter object to send tweets
        self.twitter = Twython( app_key, 
                                app_secret, 
                                oauth_token, 
                                oauth_token_secret)
 
    # [Private] Set up streamer and filter(s)
    def __createStreamer(   self, 
                            app_key, 
                            app_secret, 
                            oauth_token, 
                            oauth_token_secret ):
        self.track_stream = ListenStreamer( self, 
                                            app_key, 
                                            app_secret,
                                            oauth_token,
                                            oauth_token_secret )
        self.track_stream.statuses.filter(track='@SFE_Fellowship')#self.track_terms)
        
    # [Public] Start streamer in a thread
    def startStreamer(self, search_terms):
        self.track_terms = [''.join([x, ' ']) for x in search_terms]
        if DEBUG > 0:
            print 'Starting listening streamer looking for: ' + self.track_terms
        self.listen_thread = threading.Thread( \
                target=self.__createStreamer, args=self.auth_args)
        self.listen_thread.daemon = True
        self.listen_thread.start()
        
    # [Public] Stop streamer
    def stopStreamer(self, timeout=None):
        self.track_stream.stop()
        self.listen_thread.join(timeout)
        del self.listen_thread

    # [Public] Send a Tweet
    def tweet(self, msg):

        # Construct the message
        time_now = time.strftime('%m/%d/%Y (%H:%M:%S)')
        msg = time_now + ' ' + msg
        if DEBUG > 0:
            print msg

        # Post to Twitter
        try:
            self.twitter.update_status(status=msg)
        except TwythonError as e:
            print e
            
    # [Public] Tweet a photo
    def tweetPhoto(self, cam, msg):

        # Take a photo
        cam.start()
        img = cam.get_image()
        pygame.image.save(img, IMG_NAME)
        cam.stop()

        # Wait for file to finish writing
        time.sleep(1)
        
        # Construct the message
        time_now = time.strftime('%m/%d/%Y (%H:%M:%S)')
        msg = time_now + ' ' + msg
        for n in NAMES:
            msg = msg + ' ' + n
        if DEBUG > 0:
            print msg

        # Post to Twitter
        try:
            fp = open(IMG_NAME, 'rb')
            image_id = self.twitter.upload_media(media=fp)
            self.twitter.update_status(media_ids=[image_id['media_id']], \
                                                                status=msg)
        except TwythonError as e:
            print e
        finally:
            fp.close()
 
################################################################################
# Functions
################################################################################

# Handle ctrl-C events
def signalHandler(signal, frame):
    global g_mainloop
    if DEBUG > 0:
        print 'Ctrl-C pressed. Exiting nicely.'
    g_mainloop = False
    
# Let someone in or out of the airlock
def openDoor(p, w_ch, reed):

    # Unlock the door
    if DEBUG > 0:
        print 'Unlocking inner door.'
    bleSend(p, w_ch, MSG_UNLOCK)

    # Wait for that door to be opened and then closed
    if DEBUG > 0:
        print 'Waiting for the door to be opened...'
    while reed.read() == 0
        pass
    time.sleep(1)
    if DEBUG > 0:
        print 'Waiting for the door to be closed...'
    while reed.read() == 1
        pass
    time.sleep(2)
    bleSend(p, w_ch, MSG_LOCK)
    
# Send a message to a Lockitron
def bleSend(p, w_ch, msg):
    msg = struct.pack('i', msg)
    w_ch.write(msg)
  
################################################################################
# Main
################################################################################

def main():

    global g_mainloop

    # Initialize GPIO
    in_success = mraa.Gpio(SUCCESS_PIN)
    in_failure = mraa.Gpio(FAILURE_PIN)
    in_status_0 = mraa.Gpio(STATUS_PIN_0)
    in_status_1 = mraa.Gpio(STATUS_PIN_1)
    doorbell = mraa.Gpio(DOORBELL_PIN)
    reed_outer = mraa.Gpio(REED_OUTER_PIN)
    reed_inner = mraa.Gpio(REED_INNER_PIN)
    deny_button = mraa.Gpio(DENY_PIN)
    approve_button = mraa.Gpio(APPROVE_PIN)
    prev_success = 0
    prev_failure = 0
    prev_approve = 0
    prev_doorbell = 0
    prev_deny = 0
    
    # Create Bluetooth connections to the RFduinos on the doors
    if DEBUG > 0:
        print 'Connecting to RFduinos...'
    inner_door = Peripheral(INNER_ADDR, 'random')
    outer_door = Peripheral(OUTER_ADDR, 'random')
    
    # Create handles to the Bluetooth read and write characteristics
    inner_r_ch = inner_door.getCharacteristics(uuid=READ_UUID)[0]
    inner_w_ch = inner_door.getCharacteristics(uuid=WRITE_UUID)[0]
    outer_r_ch = outer_door.getCharacteristics(uuid=READ_UUID)[0]
    outer_w_ch = outer_door.getCharacteristics(uuid=WRITE_UUID)[0]
    
    # Set up camera
    pygame.camera.init()
    cam = pygame.camera.Camera(pygame.camera.list_cameras()[0])
    
    # Connect to Twitter and start listening
    if DEBUG > 0:
        print 'Connecting to Twitter...'
    tf = TweetFeed({'app_key': APP_KEY, \
                    'app_secret': APP_SECRET, \
                    'oauth_token': OAUTH_TOKEN, \
                    'oauth_token_secret': OAUTH_TOKEN_SECRET})
    tf.startStreamer([HANDLE])
    
    # Send a good morning Tweet
    tf.tweet(ONLINE_MSG)

    # Register 'ctrl+C' signal handler
    signal.signal(signal.SIGINT, signalHandler)

    # Main loop
    g_mainloop = True
    if DEBUG > 0:
        print 'Starting door'
    while g_mainloop:
        
        # Poll pins for success or failure (falling edge)
        state_success = in_success.read()
        state_failure = in_failure.read()
        state_doorbell = doorbell.read()
        state_deny = deny_button.read()
        state_approve = approve_button.read()
        
        # Look for success in access panel
        if (state_success == 0) and (prev_success == 1):
            person_ind = 3 - ((2 * in_status_1.read()) + in_status_0.read())
            if DEBUG > 0:
                print 'Success!'
                print 'Person = ' + NAMES[person_ind]
            tf.tweet(SUCCESS_MSG + NAMES[person_ind])
            
            # Make sure we have a BLE connection first
            #ble_state = inner_door.status()['state'][0]
            #while ble_state != 'conn':
            #    if DEBUG > 0:
            #        print 'Inner door disconnected. Trying to connect...'
            #    try:
            #        inner_door.connect(INNER_ADDR, 'random')
            #    except BTLEException as e:
            #        print 'Could not connect'
            openDoor(inner_door, inner_w_ch, reed_inner)

        # Look for failure in access panel
        elif (state_failure == 0) and (prev_failure == 1):
            if DEBUG > 0:
                print 'Fail.'
            tf.tweetPhoto(cam, FAILURE_MSG)
            
        # Look for doorbell push
        elif (state_doorbell == 0) and (prev_doorbell == 1):
            if DEBUG > 0:
                print 'Doorbell pressed.'
            openDoor(outer_door, outer_w_ch, reed_outer)
            
        # Look for deny button push
        elif (state_deny == 0) and (prev_deny == 1):
            if DEBUG > 0:
                print 'DENIED. Go away, and never come back.'
            openDoor(outer_door, outer_w_ch, reed_outer)
            
        # Look for an approve button push
        elif (state_approve == 0) and (prev_approve == 1):
            if DEBUG > 0:
                print 'APPROVED. You may enter.'
            openDoor(inner_door, inner_w_ch, reed_inner)
        
        prev_success = state_success
        prev_failure = state_failure
        prev_doorbell = state_doorbell
        prev_deny = state_deny
        prev_approve = state_approve
                
    # Outside of main loop. Cleanup and cuddles.
    if DEBUG > 0:
        print 'Cleaning up.'
    tf.stopStreamer()
    pygame.camera.quit()
    pygame.quit()
                
# Run main
main()
