import math
from enum import Enum
import matplotlib.pyplot as plt
import numpy as np

show_animation = True

def dwa_control(x, config, goal, ob):
    dw = calc_dynamic_window(x, config)
    u, trajectory = calc_control_and_trajectory(x, dw, config, goal, ob)
    return u, trajectory

class RobotType(Enum):
    circle = 0
    rectangle = 1

class Config:
    def __init__(self):
        # Robot parameters (updated for bicycle model)
        self.max_speed = 1.0  # [m/s]
        self.min_speed = -0.5  # [m/s]
        self.max_steering_angle = 30.0 * math.pi / 180.0  # [rad] Max steering angle
        self.max_accel = 0.2  # [m/ss]
        self.max_steering_rate = 20.0 * math.pi / 180.0  # [rad/s] Max steering change rate
        self.v_resolution = 0.01  # [m/s]
        self.steering_resolution = 1.0 * math.pi / 180.0  # [rad]
        self.dt = 0.1  # [s] Time tick
        self.predict_time = 3.0  # [s]
        self.to_goal_cost_gain = 0.15
        self.speed_cost_gain = 1.0
        self.obstacle_cost_gain = 1.0
        self.robot_stuck_flag_cons = 0.001
        self.robot_type = RobotType.circle
        self.robot_radius = 1.0  # [m] for collision check
        self.robot_width = 0.5  # [m]
        self.robot_length = 1.2  # [m]
        self.wheelbase = 0.8  # [m] Distance between front and rear axles (bicycle model)
        self.ob = np.array([[-1, -1], [0, 2], [4.0, 2.0], [5.0, 4.0], [5.0, 5.0],
                            [5.0, 6.0], [5.0, 9.0], [8.0, 9.0], [7.0, 9.0], [8.0, 10.0],
                            [9.0, 11.0], [12.0, 13.0], [12.0, 12.0], [15.0, 15.0], [13.0, 13.0]])

    @property
    def robot_type(self):
        return self._robot_type

    @robot_type.setter
    def robot_type(self, value):
        if not isinstance(value, RobotType):
            raise TypeError("robot_type must be an instance of RobotType")
        self._robot_type = value

config = Config()

def motion(x, u, dt, wheelbase):
    """
    Bicycle model motion: [x, y, theta, v, delta]
    u = [v, delta] (velocity, steering angle)
    """
    x_new = x.copy()
    v = u[0]  # Velocity
    delta = u[1]  # Steering angle
    theta = x[2]  # Yaw angle

    # Bicycle model equations
    x_new[0] += v * math.cos(theta) * dt  # x position
    x_new[1] += v * math.sin(theta) * dt  # y position
    x_new[2] += (v / wheelbase) * math.tan(delta) * dt  # yaw (theta)
    x_new[3] = v  # Update velocity
    x_new[4] = delta  # Update steering angle

    return x_new

def calc_dynamic_window(x, config):
    """
    Dynamic window based on current state x = [x, y, theta, v, delta]
    """
    Vs = [config.min_speed, config.max_speed, -config.max_steering_angle, config.max_steering_angle]
    Vd = [x[3] - config.max_accel * config.dt, x[3] + config.max_accel * config.dt,
          x[4] - config.max_steering_rate * config.dt, x[4] + config.max_steering_rate * config.dt]
    dw = [max(Vs[0], Vd[0]), min(Vs[1], Vd[1]), max(Vs[2], Vd[2]), min(Vs[3], Vd[3])]
    return dw

def predict_trajectory(x_init, v, delta, config):
    x = np.array(x_init)
    trajectory = np.array(x)
    time = 0
    while time <= config.predict_time:
        x = motion(x, [v, delta], config.dt, config.wheelbase)
        trajectory = np.vstack((trajectory, x))
        time += config.dt
    return trajectory

def calc_control_and_trajectory(x, dw, config, goal, ob):
    x_init = x[:]
    min_cost = float("inf")
    best_u = [0.0, 0.0]
    best_trajectory = np.array([x])

    for v in np.arange(dw[0], dw[1], config.v_resolution):
        for delta in np.arange(dw[2], dw[3], config.steering_resolution):
            trajectory = predict_trajectory(x_init, v, delta, config)
            to_goal_cost = config.to_goal_cost_gain * calc_to_goal_cost(trajectory, goal)
            speed_cost = config.speed_cost_gain * (config.max_speed - trajectory[-1, 3])
            ob_cost = config.obstacle_cost_gain * calc_obstacle_cost(trajectory, ob, config)
            final_cost = to_goal_cost + speed_cost + ob_cost

            if min_cost >= final_cost:
                min_cost = final_cost
                best_u = [v, delta]
                best_trajectory = trajectory
                if abs(best_u[0]) < config.robot_stuck_flag_cons and abs(x[3]) < config.robot_stuck_flag_cons:
                    best_u[1] = -config.max_steering_angle  # Avoid getting stuck

    return best_u, best_trajectory

def calc_obstacle_cost(trajectory, ob, config):
    ox = ob[:, 0]
    oy = ob[:, 1]
    dx = trajectory[:, 0] - ox[:, None]
    dy = trajectory[:, 1] - oy[:, None]
    r = np.hypot(dx, dy)

    if config.robot_type == RobotType.rectangle:
        yaw = trajectory[:, 2]
        rot = np.array([[np.cos(yaw), -np.sin(yaw)], [np.sin(yaw), np.cos(yaw)]])
        rot = np.transpose(rot, [2, 0, 1])
        local_ob = ob[:, None] - trajectory[:, 0:2]
        local_ob = local_ob.reshape(-1, local_ob.shape[-1])
        local_ob = np.array([local_ob @ x for x in rot])
        local_ob = local_ob.reshape(-1, local_ob.shape[-1])
        upper_check = local_ob[:, 0] <= config.robot_length / 2
        right_check = local_ob[:, 1] <= config.robot_width / 2
        bottom_check = local_ob[:, 0] >= -config.robot_length / 2
        left_check = local_ob[:, 1] >= -config.robot_width / 2
        if (np.logical_and(np.logical_and(upper_check, right_check),
                           np.logical_and(bottom_check, left_check))).any():
            return float("Inf")
    elif config.robot_type == RobotType.circle:
        if np.array(r <= config.robot_radius).any():
            return float("Inf")

    min_r = np.min(r)
    return 1.0 / min_r

def calc_to_goal_cost(trajectory, goal):
    dx = goal[0] - trajectory[-1, 0]
    dy = goal[1] - trajectory[-1, 1]
    error_angle = math.atan2(dy, dx)
    cost_angle = error_angle - trajectory[-1, 2]
    cost = abs(math.atan2(math.sin(cost_angle), math.cos(cost_angle)))
    return cost

def plot_arrow(x, y, yaw, length=0.5, width=0.1):
    plt.arrow(x, y, length * math.cos(yaw), length * math.sin(yaw),
              head_length=width, head_width=width)
    plt.plot(x, y)

def plot_robot(x, y, yaw, config):
    if config.robot_type == RobotType.rectangle:
        outline = np.array([[-config.robot_length / 2, config.robot_length / 2,
                             config.robot_length / 2, -config.robot_length / 2,
                             -config.robot_length / 2],
                            [config.robot_width / 2, config.robot_width / 2,
                             -config.robot_width / 2, -config.robot_width / 2,
                             config.robot_width / 2]])
        Rot1 = np.array([[math.cos(yaw), math.sin(yaw)],
                         [-math.sin(yaw), math.cos(yaw)]])
        outline = (outline.T.dot(Rot1)).T
        outline[0, :] += x
        outline[1, :] += y
        plt.plot(np.array(outline[0, :]).flatten(),
                 np.array(outline[1, :]).flatten(), "-k")
    elif config.robot_type == RobotType.circle:
        circle = plt.Circle((x, y), config.robot_radius, color="b")
        plt.gcf().gca().add_artist(circle)
        out_x, out_y = (np.array([x, y]) +
                        np.array([np.cos(yaw), np.sin(yaw)]) * config.robot_radius)
        plt.plot([x, out_x], [y, out_y], "-k")

def main(gx=10.0, gy=10.0, robot_type=RobotType.circle):
    #print(__file__ + " start!!")
    # Initial state [x, y, theta, v, delta]
    x = np.array([0.0, 0.0, math.pi / 8.0, 0.0, 0.0])  # Added delta
    goal = np.array([gx, gy])

    config.robot_type = robot_type
    trajectory = np.array(x)
    ob = config.ob

    while True:
        u, predicted_trajectory = dwa_control(x, config, goal, ob)
        x = motion(x, u, config.dt, config.wheelbase)  # Simulate with bicycle model
        trajectory = np.vstack((trajectory, x))

        if show_animation:
            plt.cla()
            plt.gcf().canvas.mpl_connect('key_release_event',
                                         lambda event: [exit(0) if event.key == 'escape' else None])
            plt.plot(predicted_trajectory[:, 0], predicted_trajectory[:, 1], "-g")
            plt.plot(x[0], x[1], "xr")
            plt.plot(goal[0], goal[1], "xb")
            plt.plot(ob[:, 0], ob[:, 1], "ok")
            plot_robot(x[0], x[1], x[2], config)
            plot_arrow(x[0], x[1], x[2])
            plt.axis("equal")
            plt.grid(True)
            plt.pause(0.0001)

        dist_to_goal = math.hypot(x[0] - goal[0], x[1] - goal[1])
        if dist_to_goal <= config.robot_radius:
            print("Goal!!")
            break

    print("Done")
    if show_animation:
        plt.plot(trajectory[:, 0], trajectory[:, 1], "-r")
        plt.pause(0.0001)
        plt.show()

if __name__ == '__main__':
    main(robot_type=RobotType.rectangle)