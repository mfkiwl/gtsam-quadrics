# import standard libraries
import os
import sys
import numpy as np
from enum import Enum
sys.path.append('/home/lachness/.pyenv/versions/382_generic/lib/python3.8/site-packages/')
import cv2

# import custom libraries
sys.dont_write_bytecode = True
from base.containers import Detections
from visualization.drawing import CV2Drawing

# import gtsam and extension
import gtsam
import gtsam_quadrics


class BoxTracker(object):
    """
    Wrapper around cv2.tracker to convert box types and control tracker type.
    that allows us to stop using the tracker
    if it's failed in the past. 
    """

    def __init__(self, image, box, tracker_type):
        self.tracker_type = tracker_type
        self.tracker = self.new_tracker()
        try:
            self.tracker.init(image, self.to_cvbox(box))
        except:
            print('tracker wont init, box: ', self.to_cvbox(box))
            exit()
    
    @staticmethod
    def to_cvbox(box):
        return (box.xmin(), box.ymin(), box.xmax()-box.xmin(), box.ymax()-box.ymin())

    @staticmethod
    def from_cvbox(tlwh):
        return gtsam_quadrics.AlignedBox2(tlwh[0], tlwh[1], tlwh[0]+tlwh[2], tlwh[1]+tlwh[3])

    def new_tracker(self):
        if self.tracker_type == 'BOOSTING':
            return cv2.TrackerBoosting_create()
        elif self.tracker_type == 'MIL':
            return cv2.TrackerMIL_create()
        elif self.tracker_type == 'KCF':
            return cv2.TrackerKCF_create()
        elif self.tracker_type == 'TLD':
            return cv2.TrackerTLD_create()
        elif self.tracker_type == 'MEDIANFLOW':
            return cv2.TrackerMedianFlow_create()
        elif self.tracker_type == 'GOTURN':
            return cv2.TrackerGOTURN_create()
        elif self.tracker_type == 'MOSSE':
            return cv2.TrackerMOSSE_create()
        elif self.tracker_type == 'CSRT':
            return cv2.TrackerCSRT_create()
        else:
            raise ValueError('BoxTracker new_tracker called with unknown self.tracker_type')

    def update(self, image):    
        ok, cvbox = self.tracker.update(image)
        box = self.from_cvbox(cvbox)
        return ok, box

class ObjectTracker(object):
    """
    ObjectTracker will track objects frame to frame,
    Automatically becomes inactive if:
        - not associated in n updates 
        - not ok for n updates 
        - too many trackers
    """
    def __init__(self, image, box, tracker_type):

        # settings
        self.tracker_type = tracker_type
        self.n_active_trackers = 1
        
        # create a new box tracker 
        self.trackers = [BoxTracker(image, box, self.tracker_type)]
        self.predictions = []
        self.alive = True

    def update(self, image):
        # clear previous predictions
        self.predictions = []
        
        # update most recent trackers
        for tracker in self.trackers[-self.n_active_trackers:]:
            ok, box = tracker.update(image)
            if ok:
                self.predictions.append(box)

    def compatability(self, box):
        """ Returns (best_iou, best_prediction) """
        if len(self.predictions) == 0:
            return (0.0, None)
        ious = [[box.iou(predicted_box), predicted_box] for predicted_box in self.predictions]
        return max(ious, key=lambda x: x[0])

    def add_tracker(self, box, image):
        tracker = BoxTracker(image, box, self.tracker_type)
        self.trackers.append(tracker)



# class ObjectTracker(object):
#     def __init__(self, image, box):









class DataAssociation(object):

    """
    We attempt to track objects until an object can be initialized.
    From then we use the existing map first to associate new measurements. 
    TODO: turn trackers off 
    TODO: enable multiple box trackers
    TODO: pass updateable version of map to constructor
    """

    def __init__(self, calibration, config):
        self.calibration = calibration
        self.object_trackers = {}
        self.object_count = 0

        # settings 
        self.iou_thresh = config['DataAssociation.iou_thresh']
        self.object_limit = config['DataAssociation.object_limit']
        self.tracker_type = config['DataAssociation.tracker_type']


    def associate(self, image, image_detections, camera_pose, pose_key, map, visualize=False, verbose=False):
        associated_detections = Detections()

        # update active trackers with new image 
        for object_key, object_tracker in self.object_trackers.items():
            if object_tracker.alive:

                # update image
                object_tracker.update(image)

        if visualize:
            img = image.copy()
            drawing = CV2Drawing(img)

        if verbose:
            associations = []

        for detection in image_detections:

            # associate single measurement
            object_key, association_type, predicted_box = self.associate_detection(image, detection, camera_pose, map)
            if association_type == 'failed':
                continue
            
            # append association detection
            associated_detections.add(detection, pose_key, object_key)

            if visualize:
                if association_type == 'map' or association_type == 'tracker':
                    drawing.box(detection.box, (0,0,255))
                    color = (0,255,0) if association_type == 'map' else (255,255,0)
                    drawing.box_and_text(predicted_box, (0,255,0), association_type, (0,0,0))
                if association_type == 'new':
                    drawing.box(detection.box, (0,0,255))

            if verbose:
                associations.append(association_type)

        if visualize:
            cv2.imshow('data-association', img)
            cv2.waitKey(1)

        # TODO: get actual estimate for number of active trackers
        if verbose:
            print('\n --- Data-association --- ')
            print('  active_trackers: {}'.format(np.sum([t.n_active_trackers for t in self.object_trackers.values() if t.alive])))
            print('  map_objects:     {}'.format(len(map)))
            print('  measurements:    {}'.format(len(image_detections)))
            print('      tracker: {}'.format(len([t for t in associations if t=='tracker'])))
            print('      map:     {}'.format(len([t for t in associations if t=='map'])))
            print('      new:     {}'.format(len([t for t in associations if t=='new'])))
            
        return associated_detections


    def associate_detection(self, image, detection, pose, map):
        """ 
            Tries to associate detection with map and object trackers.
            If associated with tracker, updates tracker with new measurement. 
            returns (associated_key, association_type) 

            association_types: [map, tracker, new, failed]
            TODO: remove nasty list(dict.keys())
            TODO: use a datatype that will help us get the best predicted box
        """
        compatabilities = []

        # calculate compatability with current map 
        for object_key, quadric in map.items():

            # TODO: catch projection failures 
            dual_conic = gtsam_quadrics.QuadricCamera.project(quadric, pose, self.calibration)
            predicted_box = dual_conic.bounds()
            iou = detection.box.iou(predicted_box)

            # append to compatabilities
            compatabilities.append({
                'compatability': iou,
                'object_key': object_key,
                'type': 'map',
            })

        # calculate compatability with object trackers 
        for object_key, object_tracker in self.object_trackers.items():
            if object_tracker.alive:
                comp, predicted_box = object_tracker.compatability(detection.box)

                # append to compatabilities
                compatabilities.append({
                    'compatability': comp,
                    'object_key': object_key,
                    'type': 'tracker',
                })

        if len(compatabilities) > 0:

            # get the best association
            best_frame = max(compatabilities, key=lambda x: x['compatability'])
            
            # associate with map
            if best_frame['compatability'] >= self.iou_thresh and best_frame['type'] == 'map':
                return best_frame['object_key']
                
            # associate with tracker
            elif best_frame['compatability'] >= self.iou_thresh and best_frame['type'] == 'tracker':
                best_tracker = self.object_trackers[best_frame['object_key']]
                best_tracker.add_tracker(detection.box, image)
                return best_frame['object_key']

        # otherwise create new tracker
        # get a new object key
        object_key = self.object_count
        self.object_count += 1

        # create a new tracker
        new_tracker = ObjectTracker(image, detection.box, self.tracker_type)
        self.object_trackers[object_key] = new_tracker

        return object_key