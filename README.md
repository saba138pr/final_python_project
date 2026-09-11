# BLE 8-Channel Live Signal Monitor

#### Video Demo:
[https://youtu.be/A-1E2XDo_MQ]

#### Description:

BLE 8-Channel Live Signal Monitor is a Python application developed as my CS50P final project. The application receives real-time data from a Bluetooth Low Energy device, displays eight signals in real time, monitors the transmission performance, detects possible data loss, and saves the received data to a CSV file.

The project was created to test a BLE system designed for high-rate data transmission. Each received frame contains eight channels, with three bytes used for each channel, resulting in 24 bytes per frame. BLE notifications can contain multiple frames, so the program validates the packet size, separates the notification into individual frames, and processes each frame.

The project uses the Bleak library for BLE communication. The `notification_handler` function receives notifications and passes valid frames to `process_frame`. This function decodes the three-byte channel values, updates NumPy buffers used for live plotting, and checks the counter sequence to detect missing samples, counter jumps, and counter overflow.

The application also calculates transmission statistics, including sample rate, notification rate, and throughput. The graphical interface is implemented with PyQt5 through PyQtGraph and displays eight live plots together with the current transmission statistics. BLE communication runs in an asyncio event loop on a separate thread so that BLE data reception and the graphical interface can operate at the same time.

The `open_csv` and `save_frame_to_csv` functions handle data logging. A CSV file is created when the application starts, and every processed frame is saved with its sample index, counter, and eight channel values. When the user stops the application, the CSV file is safely closed and final statistics are displayed.

### Files

- `project.py`: Main application. It contains the BLE connection, notification handling, frame processing, data-loss detection, CSV logging, rate statistics, and graphical interface.
- `test_project.py`: Pytest tests for the main data-processing and packet-handling functions.
- `requirements.txt`: Python packages required to install and run the project.

### Design Choices

NumPy buffers are used for the live signals because the application continuously updates eight channels. A lock is used for CSV access and another lock protects the rate-statistics data. The BLE event loop is placed in a separate thread so that asynchronous BLE communication does not block the PyQtGraph graphical interface.

The counter included in the received data is used as a simple way to identify missing samples. The application compares each new counter with the expected next value and records the number of missing samples when a gap is detected.
