/* ----------------------------------------------------------------------------

 * QuadricSLAM Copyright 2020, ARC Centre of Excellence for Robotic Vision, Queensland University of Technology (QUT)
 * Brisbane, QLD 4000
 * All Rights Reserved
 * Authors: Lachlan Nicholson, et al. (see THANKS for the full author list)
 * See LICENSE for the license information

 * -------------------------------------------------------------------------- */

/**
 * @file System.cpp
 * @date Apr 14, 2020
 * @author Lachlan Nicholson
 * @brief code to operate the quadric slam library on a dataset
 */

/**
 * A simple example with multiple camera positions and quadric landmarks
 *  - graph provided with true box measurements, from projecting quadric into image at each frame
 *  - graph provided with true odometry measurements
 *  - initial estimate given perturbed trajectory
 *  - initial estimate given true quadrics
 */

#include <quadricslam/geometry/ConstrainedDualQuadric.h>
#include <quadricslam/geometry/AlignedBox2.h>
#include <quadricslam/geometry/QuadricCamera.h>
#include <quadricslam/geometry/BoundingBoxFactor.h>

#include <gtsam/nonlinear/NonlinearFactorGraph.h>
#include <gtsam/nonlinear/Values.h>
#include <gtsam/nonlinear/LevenbergMarquardtOptimizer.h>
#include <gtsam/nonlinear/LevenbergMarquardtParams.h>
#include <gtsam/geometry/Pose3.h>
#include <gtsam/geometry/CalibratedCamera.h>
#include <gtsam/slam/BetweenFactor.h>

#include <random>
#include <string>
#include <iostream>

#define ODOM_SD 0.01
#define QUAD_SD 0.1
#define BOX_SD 3

using namespace gtsam;
using namespace std;

int main(void) {

    // create empty graph / estimate
    NonlinearFactorGraph graph;
    Values initialEstimate;

    // define calibration
    boost::shared_ptr<Cal3_S2> calibration(new Cal3_S2(525.0, 525.0, 0.0, 320.0, 240.0));

    // define noise models 
    boost::shared_ptr<noiseModel::Diagonal> odomNoiseModel = noiseModel::Diagonal::Sigmas(Vector6::Ones()*ODOM_SD);
    boost::shared_ptr<noiseModel::Diagonal> boxNoiseModel = noiseModel::Diagonal::Sigmas(Vector4::Ones()*BOX_SD);

    // define key poses
    vector<Pose3> trajectory;
    trajectory.push_back(gtsam::CalibratedCamera::LookatPose(Point3(10,0,0), Point3(), Point3(0,0,1)));
    trajectory.push_back(gtsam::CalibratedCamera::LookatPose(Point3(0,-10,0), Point3(), Point3(0,0,1)));
    trajectory.push_back(gtsam::CalibratedCamera::LookatPose(Point3(-10,0,0), Point3(), Point3(0,0,1)));
    trajectory.push_back(gtsam::CalibratedCamera::LookatPose(Point3(0,10,0), Point3(), Point3(0,0,1)));
    trajectory.push_back(gtsam::CalibratedCamera::LookatPose(Point3(10,0,0), Point3(), Point3(0,0,1)));

    // define quadrics
    vector<ConstrainedDualQuadric> quadrics;
    quadrics.push_back(ConstrainedDualQuadric(Pose3(), Vector3(1.,2.,3.)));
    quadrics.push_back(ConstrainedDualQuadric(Pose3(Rot3(), Point3(0.1,0.1,0.1)), Vector3(1.,2.,3.)));

    // add trajectory estimate
    for (unsigned i = 0; i < trajectory.size(); i++) {

        // add a perturbation to initial pose estimates to simulate noise
        Pose3 perturbedPose = trajectory[i].compose(Pose3(Rot3().rodriguez(0.1,0.1,0.1), Point3(0.1,0.2,0.3)));
        initialEstimate.insert(Symbol('x', i), perturbedPose);
    }

    // add quadric estimate
    for (unsigned i = 0; i < quadrics.size(); i++) {
        initialEstimate.insert(Symbol('q', i), quadrics[i]);
    }
    
    // add relative poses to graph as odometry
    for (unsigned i = 0; i < trajectory.size()-1; i++) {
        Pose3 relativePose = trajectory[i].between(trajectory[i+1]);
        BetweenFactor<Pose3> bf(Symbol('x', i), Symbol('x', i+1), relativePose);
        graph.add(bf);
    }

    // reproject true quadrics into each true pose
    for (unsigned j = 0; j < quadrics.size(); j++) {
        for (unsigned i = 0; i < trajectory.size(); i++) {
            DualConic conic = QuadricCamera::project(quadrics[j], trajectory[i], calibration);
            AlignedBox2 bounds = conic.bounds();
            BoundingBoxFactor bbf(bounds, calibration, Symbol('x', i), Symbol('q', j), boxNoiseModel);
            graph.add(bbf);
        }
    }

    // define lm parameters
    LevenbergMarquardtParams parameters;
    parameters.setVerbosityLM("SUMMARY"); // SILENT = 0, SUMMARY, TERMINATION, LAMBDA, TRYLAMBDA, TRYCONFIG, DAMPED, TRYDELTA
    parameters.setRelativeErrorTol(1e-10); ///< stop iterating when change in error between steps is less than this
    parameters.setAbsoluteErrorTol(1e-8); ///< stop when cost-costchange < tol
    parameters.setMaxIterations(100); 
    // parameters.setlambdaInitial(1e-5);
    // parameters.setlambdaUpperBound(1e10) ///< defaults to 1e5
    // parameters.setlambdaLowerBound(0) ///< defaults to 0.0

    // build optimiser
    LevenbergMarquardtOptimizer optimizer(graph, initialEstimate, parameters);

    // optimise the graph
    Values result = optimizer.optimize();

    return 1;
}
