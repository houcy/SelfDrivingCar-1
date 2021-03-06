import io
import socket
import struct
from PIL import Image
import numpy as np
import pygame
from pygame.locals import *
import sys
import serial
import time
import pickle
import os
#import sknn.mlp

# The delay (in seconds) between successive direction commands
# Note that this delay has to be more than the time for which
# we press the control keys, set in Arduino
DELAY = 0.6


class CarHandler():
    def __init__(self):
        pygame.init()
        self.serial_port = serial.Serial('/dev/ttyACM0', 115200)
        self.setDisplay = pygame.display.set_mode((400, 300))
        self.directions = { "FORWARD_COMMAND":        1,
                            "BACKWARD_COMMAND":       2,
                            "LEFT_COMMAND":           3,
                            "RIGHT_COMMAND":          4,
                            "FORWARD_RIGHT_COMMAND":  6,
                            "FORWARD_LEFT_COMMAND":   7,
                            "BACKWARD_RIGHT_COMMAND": 8,
                            "BACKWARD_LEFT_COMMAND":  9,
                            "INCORRECT_INPUT":       -1,
                            "KEY_NOT_DOWN":          -2,
                            "EXIT":                  -3
                            }

        self.directions_log_helper = {self.directions[k]: k for k in self.directions.keys()}
        self.valid_directions = [   self.directions["FORWARD_COMMAND"]
                                  , self.directions["FORWARD_RIGHT_COMMAND"]
                                  , self.directions["FORWARD_LEFT_COMMAND"]
                                ]

    def get_input_direction(self):
        for event in pygame.event.get():
            if event.type == QUIT:
                pygame.quit()
                print "Exiting"
                return self.directions["EXIT"]
                #sys.exit()
            elif event.type == KEYDOWN:
                if pygame.key.get_pressed()[K_UP] and pygame.key.get_pressed()[K_RIGHT]:
                    return self.directions["FORWARD_RIGHT_COMMAND"]
                elif pygame.key.get_pressed()[K_UP] and pygame.key.get_pressed()[K_LEFT]:
                    return self.directions["FORWARD_LEFT_COMMAND"]
                elif pygame.key.get_pressed()[K_DOWN] and pygame.key.get_pressed()[K_RIGHT]:
                    return self.directions["BACKWARD_RIGHT_COMMAND"]
                elif pygame.key.get_pressed()[K_DOWN] and pygame.key.get_pressed()[K_LEFT]:
                    return self.directions["BACKWARD_LEFT_COMMAND"]
                elif pygame.key.get_pressed()[K_UP]:
                    return self.directions["FORWARD_COMMAND"]
                elif pygame.key.get_pressed()[K_DOWN]:
                    return self.directions["BACKWARD_COMMAND"]
                elif pygame.key.get_pressed()[K_LEFT]:
                    return self.directions["LEFT_COMMAND"]
                elif pygame.key.get_pressed()[K_RIGHT]:
                    return self.directions["RIGHT_COMMAND"]
                else:
                    return self.directions["INCORRECT_INPUT"]
            else:
                return self.directions["KEY_NOT_DOWN"]

    def send_direction(self, direction_to_send):
        if direction_to_send in self.valid_directions:
            print "Direction: ", self.directions_log_helper[direction_to_send]
            self.serial_port.write(chr(direction_to_send))

    def get_and_send_direction_to_car(self):
        d = self.get_input_direction()
        self.send_direction(d)
        return d


class ImageStreamHandler():
    def __init__(self):
        # Start a socket listening for connections on 0.0.0.0:8000 (0.0.0.0 means
        # all interfaces)
        self.server_socket = socket.socket()
        self.server_socket.bind(('192.168.43.209', 8000))
        self.server_socket.listen(0)
        self.list_of_directions = []
        self.list_of_images = []
        self.carHandler = CarHandler()

    def stream_images_and_directions(self):
        # Accept a single connection and make a file-like object out of it
        connection = self.server_socket.accept()[0].makefile('rb')
        start = time.time()
        print "start time = ", start
        count = 0
        try:
            while True:
                if time.time() - start > 50:
                    break

                # Read the length of the image as a 32-bit unsigned int. If the ength is zero, quit the loop
                image_len = struct.unpack('<L', connection.read(struct.calcsize('<L')))[0]
                if not image_len:
                    break
                # Construct a stream to hold the image data and read the image data from the connection
                image_stream = io.BytesIO()
                image_stream.write(connection.read(image_len))
                # Rewind the stream, open it as an image with PIL and do processing on it
                image_stream.seek(0)
                image = Image.open(image_stream).convert('L')
                print('Image is %dx%d' % image.size)
                ar = np.asarray(image)
                print ar.shape

                direction = self.carHandler.get_and_send_direction_to_car()
                if direction == self.carHandler.directions["EXIT"]:
                    print "Stop streaming"
                    break
                elif direction not in self.carHandler.valid_directions:
                    continue
                else:
                    self.list_of_directions.append(direction)
                    self.list_of_images.append(ar)
                    time.sleep(DELAY/2)
                    count += 1
                    print "Count: ", count
        finally:
            connection.close()
            self.server_socket.close()

    def convert_image_dimensions(self, image_array, clf_name):
        top_rows_to_discard = 20
        height = 25
        width = 40
        if clf_name is 'lr':
            ar_shape = (1, width*height)
            return np.asarray(Image.fromarray(image_array[top_rows_to_discard:,:]).resize((width, height),
                                                                                          Image.ANTIALIAS)).reshape(ar_shape)
        elif clf_name is 'cnn':
            #i = np.asarray(Image.fromarray(image_array[top_rows_to_discard:,:]).resize((width, height),
            #                                                                              Image.ANTIALIAS))
            #i = i.reshape((1,height, width))
            #return i
            return np.asarray(Image.fromarray(image_array[top_rows_to_discard:,:]).resize((width, height),
                                                                                          Image.ANTIALIAS)).reshape(1, height, width)

    def self_drive(self, classifier):
        clf = classifier['clf']
        clf_name = classifier['name']

        print clf_name

        # Accept a single connection and make a file-like object out of it
        connection = self.server_socket.accept()[0].makefile('rb')
        car_handler = CarHandler()
        try:
            for idx in range(100):
                image_len = struct.unpack('<L', connection.read(struct.calcsize('<L')))[0]
                if not image_len:
                    continue
                # Construct a stream to hold the image data and read the image data from the connection
                image_stream = io.BytesIO()
                image_stream.write(connection.read(image_len))
                # Rewind the stream, open it as an image with PIL and do processing on it
                image_stream.seek(0)
                image = Image.open(image_stream).convert('L')
                print('Image is %dx%d' % image.size)
                reshaped_array = self.convert_image_dimensions(np.asarray(image), clf_name)
                print reshaped_array.shape
                predicted_direction = clf.predict(reshaped_array/255.0) #Division is for normalization

                print "predicted_direction = ", predicted_direction
                car_handler.send_direction(predicted_direction[0,0])
                time.sleep(DELAY)
        finally:
            connection.close()
            self.server_socket.close()


def store_images_and_directions(images_and_directions):
    #data_store_path_common = '/home/shantanu/PycharmProjects/RCCar/training_images/data'
    data_store_path_common = '/home/shantanu/PycharmProjects/SelfDrivingCar/test_images/data'
    data_store_path = data_store_path_common
    data_set_count = 0
    while os.path.isfile(data_store_path):
        data_set_count += 1
        data_store_path = data_store_path_common + str(data_set_count)
        print data_set_count
        print data_store_path
    with open(data_store_path,'wb') as f:
            pickle.dump(images_and_directions, f)
    

def generate_training_data():
    ish = ImageStreamHandler()
    ish.stream_images_and_directions()
    store_images_and_directions({"Images": ish.list_of_images, "Directions": ish.list_of_directions})


def self_drive_car():
    print "SELF_DRIVE_CAR"

    # Get pickled classifier
    lr_classifier_path = '/home/shantanu/PycharmProjects/SelfDrivingCar/lr_classifier.pkl'
    cnn_classifier_path = '/home/shantanu/PycharmProjects/SelfDrivingCar/cnn_classifier.pkl'
    with open(cnn_classifier_path, 'rb') as f:
        clf = pickle.load(f)
    classifier = {'name': 'cnn', 'clf': clf}

    ish = ImageStreamHandler()
    ish.self_drive(classifier)


options = {"GENERATE_TRAINING_DATA": generate_training_data,
           "SELF_DRIVE_CAR": self_drive_car}


def main():
    # Select mode to be either
    # 1) "GENERATE_TRAINING_DATA"
    # 2) "SELF_DRIVE_CAR"

    #mode = "SELF_DRIVE_CAR"
    mode = "GENERATE_TRAINING_DATA"
    options[mode]()


if __name__ == "__main__":
    main()