import matplotlib.pyplot as plt
import numpy as np
import json
points = [(0.58, 0.107), (1, 0.17), (5, 0.9), (10, 1.8), (20, 3.5),(50, 9),(100, 18),(300, 54.9), (600, 113.4), (1000, 180)]

rpm_values, flow_rate_values = zip(*points)

coefficients = np.polyfit(rpm_values, flow_rate_values, 3)

# Extrapolate flow rates for RPM values from 1 to max rpm
extrapolated_rpm_values = np.arange(0, 1000, 0.5)
extrapolated_flow_rate_values = np.polyval(coefficients, extrapolated_rpm_values)
extrapolated_flow_rate_values = np.maximum(extrapolated_flow_rate_values, 0)  # Set negative values to 0



plt.plot(extrapolated_rpm_values, extrapolated_flow_rate_values, label='Extrapolated Flow Rate')
plt.scatter(*zip(*points), color='red', label='Calibration Points')
#plt.scatter(ret, 500, color='green', label='Desired Flow Rate')
plt.xlabel('RPM')
plt.ylabel('Flow Rate (ml/min)')
plt.title('Extrapolated Flow Rate vs RPM')
plt.legend()
plt.grid(True)
plt.show()
