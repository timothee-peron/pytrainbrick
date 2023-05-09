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

"""Utility functions to attach sensors/motors and start the whole event loop
    
    #. The decorator :class:`attach` to specify peripherals that
       connect to a hub (which enables sensing and motor control functions), 
    #. The function :func:`start` that starts running the BLE communication queue, and all the hubs, in the event-loop system

"""

import logging
import pprint
import threading
from functools import partial, wraps

from curio import run, spawn, Queue

# Local imports
from ble_queue import BLEventQ
from bleak_interface import Bleak
from hub import Hub
from sockets import bricknil_socket_server


# Actual decorator that sets up the peripheral classes
# noinspection PyPep8Naming
class attach:
    """ Class-decorator to attach peripherals onto a Hub

        Injects sub-classes of `Peripheral` as instance variables on a Hub 
        such as the PoweredUp Hub, akin to "attaching" a physical sensor or
        motor onto the Hub.

        Before you attach a peripheral with sensing capabilities, 
        you need to ensure your `Peripheral` sub-class has the matching
        call-back method 'peripheralname_change'.  

        Examples::

            @attach(PeripheralType, 
                    name="instance name", 
                    port='port', 
                    capabilities=[])

        Warnings:
            - No support for checking to make sure user put in correct parameters
            - Identifies capabilities that need a callback update handler based purely on
              checking if the capability name starts with the string "sense*"

    """

    def __init__(self, peripheral_type, **kwargs):
        # TODO: check here to make sure parameters were entered
        if logging.getLogger().getEffectiveLevel() == logging.DEBUG:
            print(f'decorating with {peripheral_type}')
        self.peripheral_type = peripheral_type
        self.kwargs = kwargs

    def __call__(self, cls):
        """
            Since the actual Hub sub-class being decorated can have __init__ params,
            we need to have a wrapper function inside here to capture the arguments
            going into that __init__ call.

            Inside that wrapper, we do the following:
            
            # Instance the peripheral that was decorated with the saved **kwargs
            # Check that any `sense_*` capabiilities in the peripheral have an 
              appropriate handler method in the hub class being decorated.
            # Instance the Hub
            # Set the peripheral instance as an instance variable on the hub via the
              `Hub.attach_sensor` method

        """

        # Define a wrapper function to capture the actual instantiation and __init__ params
        @wraps(cls)
        def wrapper_f(*args, **kwargs):
            # print(f'type of cls is {type(cls)}')
            peripheral = self.peripheral_type(**self.kwargs)

            # Ugly, but scan through and check if any of the capabilities are sense_*
            if any([cap.name.startswith('sense') for cap in peripheral.capabilities]):
                handler_name = f'{peripheral.name}_change'
                assert hasattr(cls, handler_name), f'{cls.__name__} needs a handler {handler_name}'
            # Create the hub process and attach this peripheral
            o = cls(*args, **kwargs)
            logging.debug(f"Decorating class {cls.__name__} with {self.peripheral_type.__name__}")
            o.attach_sensor(peripheral)
            return o

        return wrapper_f


async def _run_all(ble, system):
    """Curio run loop 
    """
    print('inside curio run loop')
    # Instantiate the Bluetooth LE handler/queue
    ble_q = BLEventQ(ble)
    # The web client out_going queue
    web_out_queue = Queue()
    # Instantiate socket listener
    # task_socket = await spawn(socket_server, web_out_queue, ('',25000))
    task_tcp = await spawn(bricknil_socket_server, web_out_queue, ('', 25000))
    await task_tcp.join()

    # Call the user's system routine to instantiate the processes
    await system()

    hub_tasks = []
    hub_peripheral_listen_tasks = []  # Need to cancel these at the end

    # Run the bluetooth listen queue
    task_ble_q = await spawn(ble_q.run())

    # Connect all the hubs first before enabling any of them
    for hub in Hub.hubs:
        hub.web_queue_out = web_out_queue
        task_connect = await spawn(ble_q.connect(hub))
        await task_connect.join()

    for hub in Hub.hubs:
        # Start the peripheral listening loop in each hub
        task_listen = await spawn(hub.peripheral_message_loop())
        hub_peripheral_listen_tasks.append(task_listen)

        # Need to wait here until all the ports are set
        # Use a faster timeout the first time (for speeding up testing)
        first_delay = True
        for name, peripheral in hub.peripherals.items():
            while peripheral.port is None:
                logging.info(f"Waiting for peripheral {name} to attach to a port")
                if first_delay:
                    first_delay = False
                    await sleep(0.1)
                else:
                    await sleep(1)

        # Start each hub
        task_run = await spawn(hub.run())
        hub_tasks.append(task_run)

    # Now wait for the tasks to finish
    logging.info(f'Waiting for hubs to end')

    for task in hub_tasks:
        await task.join()
    logging.info(f'Hubs end')

    for task in hub_peripheral_listen_tasks:
        await task.cancel()
    await task_ble_q.cancel()

    # Print out the port information in debug mode
    for hub in Hub.hubs:
        if hub.query_port_info:
            logging.debug(pprint.pformat(hub.port_info))


def _curio_event_run(ble, system):
    """ One line function to start the Curio Event loop, 
        starting all the hubs with the message queue to the bluetooth
        communcation thread loop.

        Args:
            ble : The Adafruit_BluefruitLE interface object
            system :  Coroutine that the user provided to instantate their system

    """
    run(_run_all(ble, system), with_monitor=False)


def start(user_system_setup_func):  # pragma: no cover
    """
        Main entry point into running everything.

        Just pass in the async co-routine that instantiates all your hubs, and this
        function will take care of the rest.  This includes:

        - Initializing the Adafruit bluetooth interface object
        - Starting a run loop inside this bluetooth interface for executing the
          Curio event loop
        - Starting up the user async co-routines inside the Curio event loop
    """

    ble = Bleak()
    # Run curio in a thread
    curry_curio_event_run = partial(_curio_event_run, ble=ble, system=user_system_setup_func)
    t = threading.Thread(target=curry_curio_event_run)
    t.start()
    print('started thread for curio')
    ble.run()


if __name__ == '__main__':
    from curio import sleep

    from hub import DuploTrainHub
    from motor import DuploTrainMotor
    from sound import DuploSpeaker
    from light import LED
    from utils import Color

    logging.basicConfig(level=logging.INFO)


    @attach(DuploTrainMotor, name='motor')
    @attach(DuploSpeaker, name="speaker")
    @attach(LED, name="light")
    class Train(DuploTrainHub):

        async def run(self):
            await self.light.set_color(Color.black)
            await self.speaker.activate_updates()

            direction = 1
            
            await self.speaker.play_sound(DuploSpeaker.sounds.water)
            await sleep(2) # n  seconds

            for i in range(2):  # Repeat this control two times
                await self.light.set_color(Color.green)
                await self.motor.ramp_speed(direction * 80, 5000)  # Ramp speed to x% over y/1000 seconds
                await self.light.set_color(Color.blue)
                await self.speaker.play_sound(DuploSpeaker.sounds.steam)
                await self.motor.ramp_speed(direction * 50, 2000)
                await self.light.set_color(Color.yellow)
                await sleep(4)
                await self.light.set_color(Color.pink)
                await self.speaker.play_sound(DuploSpeaker.sounds.horn)
                await self.light.set_color(Color.yellow)
                await sleep(4)
                await self.light.set_color(Color.red)
                await self.speaker.play_sound(DuploSpeaker.sounds.brake)
                await self.motor.ramp_speed(0, 1000)  # Brake to 0 over 0.25 second
                await self.speaker.play_sound(DuploSpeaker.sounds.station)
                await self.light.set_color(Color.white)
                await sleep(8)
                direction *= -1
                
            await self.light.set_color(Color.black)


    async def system():
        train = Train('My train')


    start(system)
