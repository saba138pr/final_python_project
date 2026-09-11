import asyncio
import csv
import os
import threading
import time

import numpy as np
from bleak import BleakClient

import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtWidgets


# ============================================================
# BLE CONFIG
# ============================================================

MAC_ADDRESS = "E5:61:EA:17:41:3A"

CHARACTERISTIC_UUID = (
    "f3641401-00b0-4240-ba50-05ca45bf8abc"
)


# ============================================================
# DATA FORMAT
# ============================================================

NUM_CHANNELS = 8

BYTES_PER_CHANNEL = 3

BYTES_PER_FRAME = NUM_CHANNELS * BYTES_PER_CHANNEL

FRAMES_PER_PACKET_MAX = 10         
EXPECTED_PACKET_SIZE_MAX = 240      


# ============================================================
# LIVE PLOT
# ============================================================

MAX_PLOT_POINTS = 2000

data_buffers = [
    np.zeros(MAX_PLOT_POINTS, dtype=np.uint32)
    for _ in range(NUM_CHANNELS)
]


# ============================================================
# CSV
# ============================================================

timestamp = int(time.time())

CSV_FILENAME = f"ble_data_{timestamp}.csv"

csv_file = None
csv_writer = None

csv_lock = threading.Lock()


# ============================================================
# STATISTICS
# ============================================================

total_notifications = 0

total_frames = 0

lost_samples = 0

bad_packets = 0

last_counter = None

first_counter = None


# ============================================================
# THROUGHPUT / RATE TRACKING   # >>> ADDED
# ============================================================

rate_lock = threading.Lock()                 # >>> ADDED

rate_window_start_time = None                 # >>> ADDED
rate_window_frames = 0                        # >>> ADDED
rate_window_notifications = 0                 # >>> ADDED
rate_window_bytes = 0                         # >>> ADDED

current_sample_rate_hz = 0.0                  # >>> ADDED  (samples/sec, i.e. Hz per channel)
current_notification_rate_hz = 0.0            # >>> ADDED  (BLE notifications/sec)
current_throughput_bps = 0.0                  # >>> ADDED  (bytes/sec)

RATE_UPDATE_INTERVAL_SEC = 1.0                # >>> ADDED  


def update_rate_stats(num_new_frames, num_new_bytes):   # >>> ADDED


    global rate_window_start_time
    global rate_window_frames
    global rate_window_notifications
    global rate_window_bytes
    global current_sample_rate_hz
    global current_notification_rate_hz
    global current_throughput_bps

    now = time.time()

    with rate_lock:

        if rate_window_start_time is None:
            rate_window_start_time = now

        rate_window_frames += num_new_frames
        rate_window_notifications += 1
        rate_window_bytes += num_new_bytes

        elapsed = now - rate_window_start_time

        if elapsed >= RATE_UPDATE_INTERVAL_SEC:

            current_sample_rate_hz = rate_window_frames / elapsed
            current_notification_rate_hz = rate_window_notifications / elapsed
            current_throughput_bps = rate_window_bytes / elapsed


            rate_window_start_time = now
            rate_window_frames = 0
            rate_window_notifications = 0
            rate_window_bytes = 0


def get_rate_stats():   # >>> ADDED
    
    with rate_lock:
        return (
            current_sample_rate_hz,
            current_notification_rate_hz,
            current_throughput_bps
        )


# ============================================================
# PROGRAM STATE
# ============================================================

stop_requested = False


# ============================================================
# OPEN CSV
# ============================================================

def open_csv():

    global csv_file
    global csv_writer

    csv_file = open(
        CSV_FILENAME,
        "w",
        newline="",
        buffering=1
    )

    csv_writer = csv.writer(csv_file)

    # Header
    csv_writer.writerow([
        "Sample_Index",
        "Counter",
        "Ch0",
        "Ch1",
        "Ch2",
        "Ch3",
        "Ch4",
        "Ch5",
        "Ch6",
        "Ch7"
    ])

    csv_file.flush()

    print()
    print("=" * 70)
    print("CSV FILE:")
    print(os.path.abspath(CSV_FILENAME))
    print("=" * 70)
    print()


# ============================================================
# CLOSE CSV
# ============================================================

def close_csv():

    global csv_file

    if csv_file is not None:

        with csv_lock:

            csv_file.flush()
            csv_file.close()

        csv_file = None

        print()
        print("=" * 70)
        print("CSV SAVED:")
        print(os.path.abspath(CSV_FILENAME))
        print("=" * 70)


# ============================================================
# SAVE FRAME TO CSV
# ============================================================

def save_frame_to_csv(counter, values):

    global total_frames

    if csv_writer is None:
        return

    row = [
        total_frames,
        counter
    ]

    row.extend(values)

    with csv_lock:

        csv_writer.writerow(row)


        csv_file.flush()

    total_frames += 1


# ============================================================
# PROCESS ONE FRAME
# ============================================================

def process_frame(frame_data):

    global last_counter
    global first_counter
    global lost_samples

    counter_values = []

    # --------------------------------------------------------
    # Decode 8 channels
    # --------------------------------------------------------

    for ch in range(NUM_CHANNELS):

        byte_idx = ch * BYTES_PER_CHANNEL

        counter_value = (
            (frame_data[byte_idx] << 16)
            |
            (frame_data[byte_idx + 1] << 8)
            |
            frame_data[byte_idx + 2]
        )

        counter_values.append(
            counter_value
        )

        # ----------------------------------------------------
        # Live Plot
        # ----------------------------------------------------

        data_buffers[ch] = np.roll(
            data_buffers[ch],
            -1
        )

        data_buffers[ch][-1] = counter_value

    current_counter = counter_values[0]

    if first_counter is None:

        first_counter = current_counter

        print(
            f"[START] First Counter = {current_counter}"
        )

    if last_counter is not None:

        MAX_COUNTER = 0xFFFFFF

        expected_counter = (
            last_counter + 1
        ) & MAX_COUNTER

        if current_counter != expected_counter:

            if current_counter > last_counter:

                missing = (
                    current_counter
                    - last_counter
                    - 1
                )

                if missing > 0:

                    lost_samples += missing

                    print(
                        f"[DATA LOSS] "
                        f"Previous={last_counter}, "
                        f"Current={current_counter}, "
                        f"Missing={missing}"
                    )

            elif (
                last_counter > 0xFFFF00
                and current_counter < 0x0000FF
            ):

                print(
                    f"[COUNTER OVERFLOW] "
                    f"{last_counter} -> "
                    f"{current_counter}"
                )

            else:

                print(
                    f"[COUNTER JUMP] "
                    f"Previous={last_counter}, "
                    f"Current={current_counter}"
                )

    last_counter = current_counter

    save_frame_to_csv(
        current_counter,
        counter_values
    )


# ============================================================
# BLE NOTIFICATION CALLBACK
# ============================================================

def notification_handler(sender, data):

    global total_notifications
    global bad_packets

    total_notifications += 1

    packet_length = len(data)

    if packet_length == 0 or (packet_length % BYTES_PER_FRAME) != 0:

        bad_packets += 1

        print(
            f"[BAD PACKET] "
            f"Notification #{total_notifications}: "
            f"Length={packet_length} "
            f"(not a multiple of {BYTES_PER_FRAME})"
        )

        return

    num_frames = packet_length // BYTES_PER_FRAME

    for frame_idx in range(num_frames):

        start = (
            frame_idx * BYTES_PER_FRAME
        )

        end = (
            start + BYTES_PER_FRAME
        )

        frame_data = data[start:end]

        process_frame(
            frame_data
        )


    # ----------------------------------------------------
    update_rate_stats(num_frames, packet_length)   # >>> ADDED


# ============================================================
# BLE CONNECTION
# ============================================================

async def main_ble():

    global stop_requested

    print()
    print("=" * 70)
    print(
        f"Connecting to BLE device:\n{MAC_ADDRESS}"
    )
    print("=" * 70)

    try:

        async with BleakClient(
            MAC_ADDRESS
        ) as client:

            print()
            print("[BLE] Connected!")

            print(
                f"[BLE] Starting notifications on:"
            )

            print(
                CHARACTERISTIC_UUID
            )

            await client.start_notify(
                CHARACTERISTIC_UUID,
                notification_handler
            )

            print()
            print("[BLE] Notifications started.")
            print("[BLE] Receiving data...")
            print()

            while client.is_connected:

                if stop_requested:

                    break

                await asyncio.sleep(
                    0.05
                )

            try:

                await client.stop_notify(
                    CHARACTERISTIC_UUID
                )

            except Exception:
                pass

    except Exception as e:

        print()
        print(
            f"[BLE ERROR] {e}"
        )

    finally:

        print()
        print("[BLE] Connection closed.")


# ============================================================
# ASYNCIO THREAD
# ============================================================

def run_ble_loop(loop):

    asyncio.set_event_loop(
        loop
    )

    try:

        loop.run_until_complete(
            main_ble()
        )

    except Exception as e:

        print(
            f"[ASYNC ERROR] {e}"
        )


# ============================================================
# LIVE PLOT WINDOW
# ============================================================

class LivePlotter(
    QtWidgets.QMainWindow
):

    def __init__(self):

        super().__init__()

        self.setWindowTitle(
            "SABA BLE - 8 Channel Live Monitor"
        )

        self.resize(
            1300,
            950
        )

        central = QtWidgets.QWidget()

        self.setCentralWidget(
            central
        )

        layout = QtWidgets.QVBoxLayout(
            central
        )

        self.win = (
            pg.GraphicsLayoutWidget()
        )

        layout.addWidget(
            self.win,
            stretch=10
        )

        self.plots = []

        self.curves = []

        colors = [
            "r",
            "g",
            "b",
            "c",
            "m",
            "y",
            "w",
            "orange"
        ]

        for ch in range(NUM_CHANNELS):

            p = self.win.addPlot(
                row=ch,
                col=0
            )

            p.showGrid(
                x=True,
                y=True
            )

            p.setLabel(
                "left",
                f"Ch {ch}"
            )

            curve = p.plot(
                pen=pg.mkPen(
                    colors[ch],
                    width=1.5
                )
            )

            self.plots.append(p)

            self.curves.append(
                curve
            )

        self.status_label = (
            QtWidgets.QLabel()
        )

        self.status_label.setStyleSheet(
            "font-size: 14px;"
            "font-weight: bold;"
        )

        layout.addWidget(
            self.status_label
        )

        # ----------------------------------------------------
        # Rate label   # >>> ADDED
        # ----------------------------------------------------

        self.rate_label = QtWidgets.QLabel()   # >>> ADDED

        self.rate_label.setStyleSheet(          # >>> ADDED
            "font-size: 13px;"                  # >>> ADDED
            "color: #2a7;"                       # >>> ADDED
        )                                        # >>> ADDED

        layout.addWidget(self.rate_label)        # >>> ADDED

        self.stop_button = (
            QtWidgets.QPushButton(
                "STOP & SAVE CSV"
            )
        )

        self.stop_button.setStyleSheet(
            "font-size: 15px;"
            "font-weight: bold;"
            "padding: 10px;"
        )

        self.stop_button.clicked.connect(
            self.stop_program
        )

        layout.addWidget(
            self.stop_button
        )

        self.timer = QtCore.QTimer()

        self.timer.timeout.connect(
            self.update_plot
        )

        self.timer.start(
            30
        )

    # ========================================================

    def update_plot(self):

        for ch in range(NUM_CHANNELS):

            self.curves[ch].setData(
                data_buffers[ch]
            )

        if last_counter is None:

            counter_text = "N/A"

        else:

            counter_text = str(
                last_counter
            )

        self.status_label.setText(
            f"Notifications: {total_notifications}    |    "
            f"Samples: {total_frames}    |    "
            f"Current Counter: {counter_text}    |    "
            f"Lost Samples: {lost_samples}    |    "
            f"Bad Packets: {bad_packets}"
        )

        # ----------------------------------------------------
        # آپدیت لیبل نرخ ارسال   # >>> ADDED
        # ----------------------------------------------------

        sample_rate, notif_rate, throughput_bps = get_rate_stats()   # >>> ADDED

        self.rate_label.setText(                                     # >>> ADDED
            f"Sample Rate: {sample_rate:.1f} samples/s    |    "     # >>> ADDED
            f"Notification Rate: {notif_rate:.1f} notif/s    |    "  # >>> ADDED
            f"Throughput: {throughput_bps:.1f} bytes/s "             # >>> ADDED
            f"({throughput_bps * 8 / 1000:.2f} kbps)"                # >>> ADDED
        )                                                             # >>> ADDED

    # ========================================================

    def stop_program(self):

        global stop_requested

        stop_requested = True

        print()
        print("=" * 70)
        print("STOP REQUESTED")
        print("=" * 70)

        self.timer.stop()

        QtCore.QTimer.singleShot(
            500,
            self.finish
        )

    # ========================================================

    def finish(self):

        close_csv()

        print()
        print("=" * 70)
        print("FINAL STATISTICS")
        print("=" * 70)

        print(
            f"Notifications received : "
            f"{total_notifications}"
        )

        print(
            f"Samples received       : "
            f"{total_frames}"
        )

        print(
            f"Lost samples            : "
            f"{lost_samples}"
        )

        print(
            f"Bad packets             : "
            f"{bad_packets}"
        )

        print(
            f"First counter           : "
            f"{first_counter}"
        )

        print(
            f"Last counter            : "
            f"{last_counter}"
        )

        print("=" * 70)

        QtWidgets.QApplication.quit()


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    open_csv()

    app = QtWidgets.QApplication(
        []
    )

    window = LivePlotter()

    window.show()

    loop = asyncio.new_event_loop()

    ble_thread = threading.Thread(
        target=run_ble_loop,
        args=(loop,),
        daemon=True
    )

    ble_thread.start()

    app.exec_()

    close_csv()