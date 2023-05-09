# Copyright 2019 Virantha N. Ekanayake 
# 
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# 
# http://www.apache.org/licenses/LICENSE-2.0
# 
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Singleton interface to the Adafruit Bluetooth library"""
import logging
import uuid

from curio import Queue, sleep, CancelledError

from message_dispatch import MessageDispatch


# Need a class to represent the bluetooth adapter provided
# by adafruit that receives messages
class BLEventQ:
    """All bluetooth comms go through this object

       Provides interfaces to connect to a device/hub, send_messages to,
       and receive_messages from.  Also abstracts away the underlying bluetooth library
       that depends on the OS (Adafruit_Bluefruit for Mac, and Bleak for Linux/Win10)

       All requests to send messages to the BLE device must be inserted into
       the :class:`bricknil.BLEventQ.q` Queue object.

    """

    def __init__(self, ble):
        self.ble = ble
        self.q = Queue()
        logging.info('using bleak')
        self.adapter = None
        # User needs to make sure adapter is powered up and on
        #    sudo hciconfig hci0 up
        self.hubs = {}

    async def run(self):
        try:
            while True:
                msg = await self.q.get()
                msg_type, hub, msg_val = msg
                await self.q.task_done()
                logging.debug(f'Got msg: {msg_type} = {msg_val}')
                await self.send_message(hub.tx, msg_val)
        except CancelledError:
            logging.info(f'Terminating and disconnecting')
            await self.ble.in_queue.put('quit')

    async def send_message(self, characteristic, msg):
        """Prepends a byte with the length of the msg and writes it to
           the characteristic

           Arguments:
              characteristic : An object from bluefruit, or if using Bleak,
                  a tuple (device, uuid : str)
              msg (bytearray) : Message with header
        """
        # Message needs to have length prepended
        length = len(msg) + 1
        values = bytearray([length] + msg)
        device, char_uuid = characteristic
        await self.ble.in_queue.put(('tx', (device, char_uuid, values)))

    async def get_messages(self, hub):
        """Instance a Message object to parse incoming messages and setup
           the callback from the characteristic to call Message.parse on the
           incoming data bytes
        """
        # Message instance to parse and handle messages from this hub
        msg_parser = MessageDispatch(hub)

        # Create a fake attach message on port 255, so that we can attach any instantiated Button listeners if present
        # msg_parser.parse(bytearray([15, 0x00, 0x04, 255, 1, Button._sensor_id, 0x00, 0, 0, 0, 0, 0, 0, 0, 0]))

        def bleak_received(sender, data):
            logging.debug(f'Bleak Raw data received: {data}')
            msg = msg_parser.parse(data)
            logging.debug('{0} Received: {1}'.format(hub.name, msg))

        def received(data):
            logging.debug(f'Adafruit_Bluefruit Raw data received: {data}')
            msg = msg_parser.parse(data)
            logging.debug('{0} Received: {1}'.format(hub.name, msg))

        device, char_uuid = hub.tx
        await self.ble.in_queue.put(('notify', (device, char_uuid, bleak_received)))

    def _check_devices_for(self, devices, name, manufacturer_id, address):
        """Check if any of the devices match what we're looking for
           
           First, check to make sure the manufacturer_id matches.  If the
           manufacturer_id is not present in the BLE advertised data from the 
           device, then fall back to the name (although this is unreliable because
           the name on the device can be changed by the user through the LEGO apps).

           Then, if address is supplied, only return a device with a matching id/name
           if it's BLE MAC address also agrees

           Returns:
              device : Matching device (None if no matches)
        """
        for device in devices:
            logging.info(f'checking manufacturer ID for device named {device.name} for {name}')
            # Get the device manufacturer id from the advertised data if present
            if device.metadata['manufacturer_id'] == manufacturer_id or device.name == name:
                if not address:
                    return device
                else:
                    ble_address = device.address
                    if address == ble_address:
                        return device
                    else:
                        logging.info(f'Address {ble_address} is not a match')
            else:
                mid = device.metadata['manufacturer_id']
                logging.info(f'No match for device with advertised data {mid}')

        return None

    async def _ble_connect(self, uart_uuid, ble_name, ble_manufacturer_id, ble_id=None, timeout=60):
        """Connect to the underlying BLE device with the needed UART UUID
        """
        # Set hub.ble_id to a specific hub id if you want it to connect to a
        # particular hardware hub instance
        if ble_id:
            logging.info(f'Looking for specific hub id {ble_id}')
        else:
            logging.info(f'Looking for first matching hub')

        try:
            found = False
            while not found and timeout > 0:
                await self.ble.in_queue.put('discover')  # Tell bleak to start discovery
                devices = await self.ble.out_queue.get()  # Wait for discovered devices
                await self.ble.out_queue.task_done()
                # Filter out no-matching uuid
                devices = [d for d in devices if d.metadata and d.metadata['uuids']]
                # devices = [d for d in devices if str(uart_uuid) in d.metadata['uuids']]
                # NOw, extract the manufacturer_id
                for device in devices:
                    assert len(device.metadata['manufacturer_data']) == 1
                    data = next(iter(device.metadata['manufacturer_data'].values()))  # Get the one and only key
                    device.metadata['manufacturer_id'] = data[1]

                device = self._check_devices_for(devices, ble_name, ble_manufacturer_id, ble_id)
                if device:
                    self.device = device
                    found = True
                else:
                    logging.info(f'Rescanning for {uart_uuid} ({timeout} tries left)')
                    timeout -= 1
                    self.device = None
                    await sleep(1)
            if self.device is None:
                raise RuntimeError('Failed to find UART device!')
        except:
            raise

    async def connect(self, hub):
        """
            We probably need a different ble_queue type per operating system,
            and try to abstract away some of these hacks.

            Todo:
                * This needs to be cleaned up to get rid of all the hacks for
                  different OS and libraries

        """
        # Connect the messaging queue for communication between self and the hub
        hub.message_queue = self.q
        logging.info(f'Starting scan for UART {hub.uart_uuid}')

        # HACK
        try:
            ble_id = uuid.UUID(hub.ble_id) if hub.ble_id else None
        except ValueError:
            # In case the user passed in a 
            logging.info(f"ble_id {hub.ble_id} is not a parseable UUID, so assuming it's a BLE network addresss")
            ble_id = hub.ble_id

        await self._ble_connect(hub.uart_uuid, hub.ble_name, hub.manufacturer_id, ble_id)

        logging.info(f"found device {self.device.name}")

        await self.ble.in_queue.put(('connect', self.device.address))
        device = await self.ble.out_queue.get()
        await self.ble.out_queue.task_done()
        hub.ble_id = self.device.address
        # logging.info(f'Device advertised: {device.characteristics}')
        hub.tx = (device,
                    hub.char_uuid)  # Need to store device because the char is not an object in Bleak, unlike Bluefruit library
        # Hack to fix device name on Windows
        if self.device.name == "Unknown" and hasattr(device._requester, 'Name'):
            self.device.name = device._requester.Name

        logging.info(f"Connected to device {self.device.name}:{hub.ble_id}")
        self.hubs[hub.ble_id] = hub

        await self.get_messages(hub)
