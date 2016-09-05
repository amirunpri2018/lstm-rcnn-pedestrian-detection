#!/usr/bin/env python

import os, glob, json, time, random
from math import ceil, floor, sqrt, exp

import numpy as np
from PIL import Image, ImageDraw

def IoU(anchor_box, truth_box):
    (y1, x1, h1, w1) = anchor_box
    (y2, x2, h2, w2) = truth_box

    intersect = max(0.0, min(y1+h1-1, y2+h2-1) - max(y1, y2)) * max(0.0, min(x1+w1-1, x2+w2-1) - max(x1, x2))

    return intersect / (h1 * w1 + h2 * w2 - intersect)

def IoU_negative(anchor_box, truth_box):
    # We return the max of two different quantity:
    # IoU, and Intersection over the anchor area
    (y1, x1, h1, w1) = anchor_box
    (y2, x2, h2, w2) = truth_box

    intersect = max(0.0, min(y1+h1-1, y2+h2-1) - max(y1, y2)) * max(0.0, min(x1+w1-1, x2+w2-1) - max(x1, x2))

    return max(intersect / (h1 * w1 + h2 * w2 - intersect), intersect / (h1 * w1))

class Anchors:
    def __init__(self, heights, width_to_height_ratios):
        self.num = len(heights) * len(width_to_height_ratios)

        self.heights = []
        self.widths = []
        for h in heights:
            for r in width_to_height_ratios:
                w = float(h) * float(r)
                self.heights.append(float(h))
                self.widths.append(w)

class CaltechDataset:
    ### Input & output sizes ###
    INPUT_SIZE = (480, 640)
    OUTPUT_SIZE = (30, 40)
    OUTPUT_CELL_SIZE = float(INPUT_SIZE[0]) / float(OUTPUT_SIZE[0])

    ### Parameters controlling the size of training, validation & testing sets ###
    RANDOM_SEED = 64464 # Used for selecting reproducable subsets
    TRAINING_SIZE = 100 # Number of testing frames kept from all available
    VALIDATION_RATIO = 1.0 / 3.0 # Ratio of training data kept for validation
    TESTING_SIZE = 100 # Number of testing frames kept from all available
    FRAME_MODULO = 30 # Modulo for selecting frames from sequences in testing

    ### Parameters controlling how the classification is created ###
    MINIMUM_VISIBLE_RATIO = 0.5 # Minimum ratio of area visible for occluded objects to be included
    MINIMUM_WIDTH = 10 # Minimum width for objects to be included
    USE_UNDESIRABLES = False # If set to true, anchors within undesirable objects (crowds, occluded pedestrians, ...) are set to be neither positive nor negative
    NEGATIVE_THRESHOLD = 0.3
    POSITIVE_THRESHOLD = 0.7

    ### Parameters controlling how examples are fed while training ###
    MINIBATCH_SIZE = 64 # Number of examples (positive, negative or neither) used per image as a minibatch

    def __init__(self, dataset_location = 'caltech-dataset/dataset'):
        self.dataset_location = dataset_location
        self.annotations = None

        self.anchors = Anchors([30, 60, 100, 200, 350], [0.41])

        self.epoch = 0
        self.training_minibatch = 0
        self.validation_minibatch = 0
        self.testing_minibatch = 0

        # self.set_training([(0, 1, 975), (3, 8, 240), (3, 8, 262), (3, 8, 279), (3, 8, 280), (3, 8, 293), (3, 8, 294), (3, 8, 295), (3, 8, 299), (3, 8, 300), (3, 8, 306), (3, 8, 308), (3, 8, 309), (3, 8, 313), (3, 8, 314), (3, 8, 315), (3, 8, 316), (3, 8, 317), (3, 8, 318), (3, 8, 321), (3, 8, 322), (3, 8, 326), (3, 8, 327), (3, 8, 334), (3, 8, 335), (3, 8, 336), (3, 8, 342), (3, 8, 345), (3, 8, 347), (3, 8, 348), (3, 8, 349), (3, 8, 350), (3, 8, 351), (3, 8, 358), (3, 8, 359), (3, 8, 360), (3, 8, 361), (3, 8, 362), (3, 8, 363), (3, 8, 364), (3, 8, 365), (3, 8, 368), (3, 8, 369), (3, 8, 370), (3, 8, 371), (3, 8, 372), (3, 8, 373), (3, 8, 374), (3, 8, 380), (3, 8, 381), (3, 8, 382), (3, 8, 391), (3, 8, 392), (3, 8, 393), (3, 8, 396), (3, 8, 397), (3, 8, 398), (3, 8, 401), (3, 8, 404), (3, 8, 410), (3, 8, 420), (3, 8, 427), (3, 8, 429), (3, 8, 430), (3, 8, 431), (3, 8, 434), (3, 8, 437), (3, 8, 443), (3, 8, 444), (3, 8, 451), (3, 8, 455), (3, 8, 456), (3, 8, 457), (3, 8, 458), (3, 8, 459), (3, 8, 460), (3, 8, 462), (3, 8, 466), (3, 8, 467), (3, 8, 478), (3, 8, 479), (3, 8, 480), (3, 8, 492), (3, 8, 493), (3, 8, 514), (3, 8, 515)])
        self.discover_training()

        self.discover_testing()

    def discover_seq(self, set_number, seq_number, skip_frames):
        num_frames = len(glob.glob(self.dataset_location + '/images/set{:02d}/V{:03d}.seq/*.jpg'.format(set_number, seq_number)))

        if skip_frames:
            num_frames = int(floor(num_frames / CaltechDataset.FRAME_MODULO))

            return [(set_number, seq_number, CaltechDataset.FRAME_MODULO * i - 1) for i in range(1, num_frames + 1)]
        else:
            return [(set_number, seq_number, i) for i in range(num_frames)]

    def discover_set(self, set_number, skip_frames = False):
        num_sequences = len(glob.glob(self.dataset_location + '/images/set{:02d}/V*.seq'.format(set_number)))

        tuples = []
        for seq_number in range(num_sequences):
            tuples += self.discover_seq(set_number, seq_number, skip_frames)

        return tuples

    def discover_training(self):
        training = []
        for set_number in range(5 + 1):
            training += self.discover_set(set_number, skip_frames = False)

        random.seed(CaltechDataset.RANDOM_SEED) # For reproducibility
        self.set_training([training[i] for i in sorted(random.sample(range(len(training)), CaltechDataset.TRAINING_SIZE))])

    def discover_testing(self):
        testing = []
        for set_number in range(6, 10 + 1):
            testing += self.discover_set(set_number, skip_frames = True)

        random.seed(CaltechDataset.RANDOM_SEED) # For reproducibility
        self.testing = [testing[i] for i in sorted(random.sample(range(len(testing)), CaltechDataset.TESTING_SIZE))]
        print('{} testing examples kept (out of {})'.format(len(self.testing), len(testing)))

    def set_training(self, training):
        # Select a portion of the training set for validation
        random.seed(CaltechDataset.RANDOM_SEED) # For reproducibility
        indices = range(len(training))
        random.shuffle(indices)
        num_training = len(training) - int(float(len(training)) * CaltechDataset.VALIDATION_RATIO)

        self.training = [training[i] for i in sorted(indices[:num_training])]
        print('{} training examples'.format(len(self.training)))

        self.validation = [training[i] for i in sorted(indices[num_training:])]
        print('{} validation examples'.format(len(self.validation)))

    def get_training_minibatch(self, input_placeholder, clas_placeholder, reg_placeholder):
        input_data, clas_negative, clas_positive, reg_positive = self.load_frame(*self.training[self.training_minibatch])
        self.training_minibatch = self.training_minibatch + 1
        if self.training_minibatch == len(self.training):
            self.training_minibatch = 0
            self.epoch += 1

        if clas_negative.shape[1] > CaltechDataset.MINIBATCH_SIZE / 2:
            selected = np.random.choice(clas_negative.shape[1], CaltechDataset.MINIBATCH_SIZE / 2, replace = False)
            clas_negative = clas_negative[:, selected]

        if clas_positive.shape[1] > CaltechDataset.MINIBATCH_SIZE / 2:
            selected = np.random.choice(clas_positive.shape[1], CaltechDataset.MINIBATCH_SIZE / 2, replace = False)
            clas_positive = clas_positive[:, selected]
            reg_positive = reg_positive[selected, :]

        clas_data = np.zeros((1, CaltechDataset.OUTPUT_SIZE[0], CaltechDataset.OUTPUT_SIZE[1], self.anchors.num, 2)) # [?, height, width, # anchors, 2]
        reg_data = np.zeros((1, CaltechDataset.OUTPUT_SIZE[0], CaltechDataset.OUTPUT_SIZE[1], self.anchors.num, 4)) # [?, height, width, # anchors, 4]

        clas_data[(0,) + tuple(clas_negative) + (0,)] = 1.0
        clas_data[(0,) + tuple(clas_positive) + (1,)] = 1.0
        reg_data[(0,) + tuple(clas_positive)] = reg_positive

        return {
            input_placeholder: input_data,
            clas_placeholder: clas_data,
            reg_placeholder: reg_data
        }

    def get_validation_minibatch(self, input_placeholder, clas_placeholder, reg_placeholder):
        input_data, clas_negative, clas_positive, reg_positive = self.load_frame(*self.validation[self.validation_minibatch])
        self.validation_minibatch = self.validation_minibatch + 1
        if self.validation_minibatch == len(self.validation):
            self.validation_minibatch = 0
            last_frame = True
        else:
            last_frame = False

        clas_data = np.zeros((1, CaltechDataset.OUTPUT_SIZE[0], CaltechDataset.OUTPUT_SIZE[1], self.anchors.num, 2)) # [?, height, width, # anchors, 2]
        reg_data = np.zeros((1, CaltechDataset.OUTPUT_SIZE[0], CaltechDataset.OUTPUT_SIZE[1], self.anchors.num, 4)) # [?, height, width, # anchors, 4]

        clas_data[(0,) + tuple(clas_negative) + (0,)] = 1.0
        clas_data[(0,) + tuple(clas_positive) + (1,)] = 1.0
        reg_data[(0,) + tuple(clas_positive)] = reg_positive

        return {
            input_placeholder: input_data,
            clas_placeholder: clas_data,
            reg_placeholder: reg_data
        }, last_frame

    def get_testing_minibatch(self, input_placeholder, clas_placeholder, reg_placeholder):
        input_data, clas_negative, clas_positive, reg_positive = self.load_frame(*self.testing[self.testing_minibatch])
        self.testing_minibatch = self.testing_minibatch + 1
        if self.testing_minibatch == len(self.testing):
            self.testing_minibatch = 0
            last_frame = True
        else:
            last_frame = False

        clas_data = np.zeros((1, CaltechDataset.OUTPUT_SIZE[0], CaltechDataset.OUTPUT_SIZE[1], self.anchors.num, 2)) # [?, height, width, # anchors, 2]
        reg_data = np.zeros((1, CaltechDataset.OUTPUT_SIZE[0], CaltechDataset.OUTPUT_SIZE[1], self.anchors.num, 4)) # [?, height, width, # anchors, 4]

        clas_data[(0,) + tuple(clas_negative) + (0,)] = 1.0
        clas_data[(0,) + tuple(clas_positive) + (1,)] = 1.0
        reg_data[(0,) + tuple(clas_positive)] = reg_positive

        return {
            input_placeholder: input_data,
            clas_placeholder: clas_data,
            reg_placeholder: reg_data
        }, last_frame

    def get_anchor_at(self, anchor_id, y, x):
        center_y = CaltechDataset.OUTPUT_CELL_SIZE * (float(y) + 0.5)
        center_x = CaltechDataset.OUTPUT_CELL_SIZE * (float(x) + 0.5)

        height = self.anchors.heights[anchor_id]
        width = self.anchors.widths[anchor_id]

        top_y = center_y - height / 2.0
        top_x = center_x - width / 2.0

        return (top_y, top_x, height, width)

    def load_annotations(self):
        if self.annotations:
            return

        with open(self.dataset_location + '/annotations.json') as json_file:
            self.annotations = json.load(json_file)

    def prepare_frame(self, set_number, seq_number, frame_number):
        self.load_annotations() # Will be needed

        # For saving
        if not os.path.isdir(self.dataset_location + '/prepared/set{:02d}/V{:03d}.seq'.format(set_number, seq_number)):
            os.makedirs(self.dataset_location + '/prepared/set{:02d}/V{:03d}.seq'.format(set_number, seq_number))

        image = Image.open(self.dataset_location + '/images/set{:02d}/V{:03d}.seq/{}.jpg'.format(set_number, seq_number, frame_number))

        input_data = np.expand_dims(np.reshape(np.array(image.getdata(), dtype = np.uint8), [image.size[1], image.size[0], 3]), axis = 0) # [?, height, width, RGB]
        np.save(self.dataset_location + '/prepared/set{:02d}/V{:03d}.seq/{}.input.npy'.format(set_number, seq_number, frame_number), input_data)

        # Retrieve objects for that frame in annotations
        try:
            objects = self.annotations['set{:02d}'.format(set_number)]['V{:03d}'.format(seq_number)]['frames']['{}'.format(frame_number)]
        except KeyError as e:
            objects = None # Simply no objects for that frame

        persons = []
        undesirables = []
        if objects:
            for o in objects:
                good = False
                pos = (o['pos'][1], o['pos'][0], o['pos'][3], o['pos'][2]) # Convert to (y, x, h, w)

                if o['lbl'] in ['person']:
                    good = True

                    # Remove objects with very small width (are they errors in labeling?!)
                    if pos[3] < CaltechDataset.MINIMUM_WIDTH:
                        good = False

                    if o['occl'] == 1:
                        if type(o['posv']) == int:
                            good = False
                        else:
                            visible_pos = (o['posv'][1], o['posv'][0], o['posv'][3], o['posv'][2]) # Convert to (y, x, h, w)
                            if visible_pos[2] * visible_pos[3] < CaltechDataset.MINIMUM_VISIBLE_RATIO * pos[2] * pos[3]:
                                good = False
                                pos = visible_pos

                if good:
                    persons.append(pos)
                elif CaltechDataset.USE_UNDESIRABLES:
                    undesirables.append(pos)

        # Move data to numpy
        persons = np.array(persons, dtype = np.float32)
        undesirables = np.array(undesirables, dtype = np.float32)

        # Compute IoUs for positive & negative examples
        IoUs = np.zeros((CaltechDataset.OUTPUT_SIZE[0], CaltechDataset.OUTPUT_SIZE[1], self.anchors.num, persons.shape[0]))
        IoUs_negatives = np.zeros((CaltechDataset.OUTPUT_SIZE[0], CaltechDataset.OUTPUT_SIZE[1], self.anchors.num, persons.shape[0] + undesirables.shape[0]))

        # Keep track of cross boundaries anchors, to remove them from training
        cross_boundaries = np.zeros((CaltechDataset.OUTPUT_SIZE[0], CaltechDataset.OUTPUT_SIZE[1], self.anchors.num), dtype = np.uint8)

        # Keep anchor positions for regression
        anchor_pos = np.zeros((CaltechDataset.OUTPUT_SIZE[0], CaltechDataset.OUTPUT_SIZE[1], self.anchors.num, 4), dtype = np.float32)

        for y in range(CaltechDataset.OUTPUT_SIZE[0]):
            for x in range(CaltechDataset.OUTPUT_SIZE[1]):
                for anchor_id in range(self.anchors.num):
                    pos = self.get_anchor_at(anchor_id, y, x)
                    anchor_pos[y, x, anchor_id] = pos

                    if pos[0] < 0 or pos[0] + pos[2] >= CaltechDataset.INPUT_SIZE[0] or pos[1] < 0 or pos[1] + pos[3] >= CaltechDataset.INPUT_SIZE[1]:
                        cross_boundaries[y, x, anchor_id] = 1.0

                    maxIoU = 0.0
                    for i in range(persons.shape[0]):
                        IoUs[y, x, anchor_id, i] = IoU(pos, persons[i])
                        # IoUs_negatives[y, x, anchor_id, i] = IoU_negative(pos, persons[i])
                        IoUs_negatives[y, x, anchor_id, i] = IoU(pos, persons[i])
                    for i in range(undesirables.shape[0]):
                        # IoUs_negatives[y, x, anchor_id, persons.shape[0] + i] = IoU_negative(pos, undesirables[i])
                        IoUs_negatives[y, x, anchor_id, persons.shape[0] + i] = IoU(pos, undesirables[i])

        clas_data = np.zeros((CaltechDataset.OUTPUT_SIZE[0], CaltechDataset.OUTPUT_SIZE[1], self.anchors.num, 2), dtype = np.uint8) # [height, width, # anchors, 2]

        # Negative examples
        if persons.shape[0] + undesirables.shape[0] > 0:
            IoUs_negatives = np.max(IoUs_negatives, axis = 3)

            clas_data[IoUs_negatives <= CaltechDataset.NEGATIVE_THRESHOLD, 0] = 1.0
        else:
            clas_data[:, :, :, 0] = 1.0

        # Positive examples
        if persons.shape[0] > 0:
            # Set best IoU for each person above threshold to create at least a positive example
            max_idx = IoUs.reshape(-1, IoUs.shape[3]).argmax(axis = 0) # Reshape IoUs for easier computation of argmax per person
            maxs = np.column_stack(np.unravel_index(max_idx, IoUs.shape[:3])) # Compute back maxima indices in regular IoUs shape
            for i in range(persons.shape[0]):
                index = tuple(maxs[i]) + (i,)
                IoUs[index] = 1.0

            max_IoUs = np.max(IoUs, axis = 3)
            argmax_IoUS = np.argmax(IoUs, axis = 3)

            clas_data[max_IoUs >= CaltechDataset.POSITIVE_THRESHOLD, 1] = 1.0
            clas_data[max_IoUs >= CaltechDataset.POSITIVE_THRESHOLD, 0] = 0.0 # We want no overlap, so positives win over negatives

        # Remove cross-boundaries
        clas_data[cross_boundaries == 1.0, 0] = 0.0
        clas_data[cross_boundaries == 1.0, 1] = 0.0

        # Compute regression for final positive examples
        if persons.shape[0] > 0:
            positive_anchor_pos = anchor_pos[clas_data[:, :, :, 1] == 1.0]
            argmax_IoUS = argmax_IoUS[clas_data[:, :, :, 1] == 1.0]
            positive_person_pos = persons[argmax_IoUS]

            reg_positive = np.zeros(positive_anchor_pos.shape, dtype = np.float32)
            reg_positive[:, 0] = (positive_person_pos[:, 0] - positive_anchor_pos[:, 0]) / positive_anchor_pos[:, 2] # t_y = (y - y_a) / h_a
            reg_positive[:, 1] = (positive_person_pos[:, 1] - positive_anchor_pos[:, 1]) / positive_anchor_pos[:, 3] # t_x = (x - x_a) / w_a
            reg_positive[:, 2] = np.log(positive_person_pos[:, 2] / positive_anchor_pos[:, 2]) # t_h = log(h / h_a)
            reg_positive[:, 3] = np.log(positive_person_pos[:, 3] / positive_anchor_pos[:, 3]) # t_w = log(w / w_a)
        else:
            reg_positive = np.zeros((0, 4), dtype = np.float32)

        clas_negative = np.where(clas_data[:, :, :, 0] == 1.0)
        np.save(self.dataset_location + '/prepared/set{:02d}/V{:03d}.seq/{}.negative.npy'.format(set_number, seq_number, frame_number), clas_negative)
        clas_positive = np.where(clas_data[:, :, :, 1] == 1.0)
        np.save(self.dataset_location + '/prepared/set{:02d}/V{:03d}.seq/{}.positive.npy'.format(set_number, seq_number, frame_number), clas_positive)
        np.save(self.dataset_location + '/prepared/set{:02d}/V{:03d}.seq/{}.reg.npy'.format(set_number, seq_number, frame_number), reg_positive)

    def show_frame(self, set_number, seq_number, frame_number):
        self.load_annotations() # Will be needed

        # Check the frame was prepared
        if not self.is_frame_prepared(set_number, seq_number, frame_number):
            self.prepare_frame(set_number, seq_number, frame_number)

        image = Image.open(self.dataset_location + '/images/set{:02d}/V{:03d}.seq/{}.jpg'.format(set_number, seq_number, frame_number))
        dr = ImageDraw.Draw(image)

        # Retrieve objects for that frame in annotations
        try:
            objects = self.annotations['set{:02d}'.format(set_number)]['V{:03d}'.format(seq_number)]['frames']['{}'.format(frame_number)]
        except KeyError as e:
            objects = None # Simply no objects for that frame

        if objects:
            for o in objects:
                pos = (o['pos'][1], o['pos'][0], o['pos'][3], o['pos'][2]) # Convert to (y, x, h, w)

                if o['lbl'] in ['person']:
                    good = True

                    # Remove objects with very small width (are they errors in labeling?!)
                    if pos[3] < CaltechDataset.MINIMUM_WIDTH:
                        good = False

                    if o['occl'] == 1:
                        if type(o['posv']) == int:
                            good = False
                        else:
                            visible_pos = (o['posv'][1], o['posv'][0], o['posv'][3], o['posv'][2]) # Convert to (y, x, h, w)
                            if visible_pos[2] * visible_pos[3] < CaltechDataset.MINIMUM_VISIBLE_RATIO * pos[2] * pos[3]:
                                good = False
                                pos = visible_pos

                    if good:
                        dr.rectangle((pos[1], pos[0], pos[1] + pos[3], pos[0] + pos[2]), outline = 'blue')
                    else:
                        dr.rectangle((pos[1], pos[0], pos[1] + pos[3], pos[0] + pos[2]), outline = 'pink')
                else:
                    dr.rectangle((pos[1], pos[0], pos[1] + pos[3], pos[0] + pos[2]), outline = 'black')

        clas_negative = np.load(self.dataset_location + '/prepared/set{:02d}/V{:03d}.seq/{}.negative.npy'.format(set_number, seq_number, frame_number))
        for i in range(clas_negative.shape[1]):
            y, x, anchor_id = clas_negative[:, i]
            dr.rectangle((CaltechDataset.OUTPUT_CELL_SIZE * x, CaltechDataset.OUTPUT_CELL_SIZE * y, CaltechDataset.OUTPUT_CELL_SIZE * (x+1) - 1, CaltechDataset.OUTPUT_CELL_SIZE * (y+1) - 1), outline = 'red')

        clas_positive = np.load(self.dataset_location + '/prepared/set{:02d}/V{:03d}.seq/{}.positive.npy'.format(set_number, seq_number, frame_number))
        for i in range(clas_positive.shape[1]):
            y, x, anchor_id = clas_positive[:, i]
            pos = self.get_anchor_at(anchor_id, y, x)
            dr.rectangle((CaltechDataset.OUTPUT_CELL_SIZE * x, CaltechDataset.OUTPUT_CELL_SIZE * y, CaltechDataset.OUTPUT_CELL_SIZE * (x+1) - 1, CaltechDataset.OUTPUT_CELL_SIZE * (y+1) - 1), outline = 'green')
            dr.rectangle((pos[1], pos[0], pos[1] + pos[3], pos[0] + pos[2]), outline = 'green')

        image.show()

    def show_results(self, set_number, seq_number, frame_number, clas_guess):
        self.load_annotations() # Will be needed

        # Check the frame was prepared
        if not self.is_frame_prepared(set_number, seq_number, frame_number):
            self.prepare_frame(set_number, seq_number, frame_number)

        image = Image.open(self.dataset_location + '/images/set{:02d}/V{:03d}.seq/{}.jpg'.format(set_number, seq_number, frame_number))
        dr = ImageDraw.Draw(image)

        # Retrieve objects for that frame in annotations
        try:
            objects = self.annotations['set{:02d}'.format(set_number)]['V{:03d}'.format(seq_number)]['frames']['{}'.format(frame_number)]
        except KeyError as e:
            objects = None # Simply no objects for that frame

        if objects:
            for o in objects:
                pos = (o['pos'][1], o['pos'][0], o['pos'][3], o['pos'][2]) # Convert to (y, x, h, w)

                if o['lbl'] in ['person']:
                    good = True

                    # Remove objects with very small width (are they errors in labeling?!)
                    if pos[3] < CaltechDataset.MINIMUM_WIDTH:
                        good = False

                    if o['occl'] == 1:
                        if type(o['posv']) == int:
                            good = False
                        else:
                            visible_pos = (o['posv'][1], o['posv'][0], o['posv'][3], o['posv'][2]) # Convert to (y, x, h, w)
                            if visible_pos[2] * visible_pos[3] < CaltechDataset.MINIMUM_VISIBLE_RATIO * pos[2] * pos[3]:
                                good = False
                                pos = visible_pos

                    if good:
                        dr.rectangle((pos[1], pos[0], pos[1] + pos[3], pos[0] + pos[2]), outline = 'blue')
                    else:
                        dr.rectangle((pos[1], pos[0], pos[1] + pos[3], pos[0] + pos[2]), outline = 'pink')
                else:
                    dr.rectangle((pos[1], pos[0], pos[1] + pos[3], pos[0] + pos[2]), outline = 'black')

        clas_guess = clas_guess.reshape((CaltechDataset.OUTPUT_SIZE[0], CaltechDataset.OUTPUT_SIZE[1], self.anchors.num))

        for y in range(clas_guess.shape[0]):
            for x in range(clas_guess.shape[1]):
                for anchor_id in range(clas_guess.shape[2]):
                    pos = self.get_anchor_at(anchor_id, y, x)

                    if clas_guess[y, x, anchor_id] == 0.0: # Negative
                        dr.rectangle((CaltechDataset.OUTPUT_CELL_SIZE * x, CaltechDataset.OUTPUT_CELL_SIZE * y, CaltechDataset.OUTPUT_CELL_SIZE * (x+1) - 1, CaltechDataset.OUTPUT_CELL_SIZE * (y+1) - 1), outline = 'red')
                    else: # Positive
                        dr.rectangle((CaltechDataset.OUTPUT_CELL_SIZE * x, CaltechDataset.OUTPUT_CELL_SIZE * y, CaltechDataset.OUTPUT_CELL_SIZE * (x+1) - 1, CaltechDataset.OUTPUT_CELL_SIZE * (y+1) - 1), outline = 'green')
                        dr.rectangle((pos[1], pos[0], pos[1] + pos[3], pos[0] + pos[2]), outline = 'green')

        image.show()

    def is_frame_prepared(self, set_number, seq_number, frame_number):
        return os.path.isfile(self.dataset_location + '/prepared/set{:02d}/V{:03d}.seq/{}.input.npy'.format(set_number, seq_number, frame_number)) and os.path.isfile(self.dataset_location + '/prepared/set{:02d}/V{:03d}.seq/{}.negative.npy'.format(set_number, seq_number, frame_number)) and os.path.isfile(self.dataset_location + '/prepared/set{:02d}/V{:03d}.seq/{}.positive.npy'.format(set_number, seq_number, frame_number)) and os.path.isfile(self.dataset_location + '/prepared/set{:02d}/V{:03d}.seq/{}.reg.npy'.format(set_number, seq_number, frame_number))

    def load_frame(self, set_number, seq_number, frame_number):
        input_data = np.load(self.dataset_location + '/prepared/set{:02d}/V{:03d}.seq/{}.input.npy'.format(set_number, seq_number, frame_number))
        clas_negative = np.load(self.dataset_location + '/prepared/set{:02d}/V{:03d}.seq/{}.negative.npy'.format(set_number, seq_number, frame_number))
        clas_positive = np.load(self.dataset_location + '/prepared/set{:02d}/V{:03d}.seq/{}.positive.npy'.format(set_number, seq_number, frame_number))
        reg_positive = np.load(self.dataset_location + '/prepared/set{:02d}/V{:03d}.seq/{}.reg.npy'.format(set_number, seq_number, frame_number))

        return input_data, clas_negative, clas_positive, reg_positive

    def prepare(self):
        for minibatch in self.training + self.validation + self.testing:
            if not self.is_frame_prepared(*minibatch):
                self.prepare_frame(*minibatch)

if __name__ == '__main__':
    caltech = CaltechDataset('dataset')
    # caltech.prepare()
    # caltech.show_frame(*caltech.training[0])
    caltech.get_training_minibatch(0, 1)
    exit(1)

    # Some statistics on the sets used
    num_negatives = 0
    num_positives = 0
    for minibatch in caltech.training:
        input_data, clas_negative, clas_positive, reg_positive = caltech.load_frame(*minibatch)
        num_negatives += clas_negative.shape[1]
        num_positives += clas_positive.shape[1]
    print('Training set:')
    print('Positive examples: {}'.format(num_positives))
    print('Negative examples: {}'.format(num_negatives))
    print('Ratio: {}'.format(float(num_positives) / float(num_positives + num_negatives)))

    num_negatives = 0
    num_positives = 0
    for minibatch in caltech.validation:
        input_data, clas_negative, clas_positive, reg_positive = caltech.load_frame(*minibatch)
        num_negatives += clas_negative.shape[1]
        num_positives += clas_positive.shape[1]
    print('Validation set:')
    print('Positive examples: {}'.format(num_positives))
    print('Negative examples: {}'.format(num_negatives))
    print('Ratio: {}'.format(float(num_positives) / float(num_positives + num_negatives)))

    num_negatives = 0
    num_positives = 0
    for minibatch in caltech.testing:
        input_data, clas_negative, clas_positive, reg_positive = caltech.load_frame(*minibatch)
        num_negatives += clas_negative.shape[1]
        num_positives += clas_positive.shape[1]
    print('Testing set:')
    print('Positive examples: {}'.format(num_positives))
    print('Negative examples: {}'.format(num_negatives))
    print('Ratio: {}'.format(float(num_positives) / float(num_positives + num_negatives)))
