"""Asset manages runtime state of a hardware component/device
& responds to certain events (Power/Thermal etc.)
"""
# **due to circuit callback signature
# pylint: disable=W0613

import logging
import time

from circuits import Component, handler
from enginecore.state.hardware import event_results
from enginecore.state.hardware.asset_definition import SUPPORTED_ASSETS
from enginecore.state.hardware import asset_events


class Asset(Component):
    """Abstract Asset Class """

    def __init__(self, state):
        super(Asset, self).__init__()
        self._state = state
        self._state_reason = asset_events.ButtonPowerUpPressed
        self.state.update_input_voltage(0)

        self.state.reset_boot_time()
        self.state.update_load(0.0)

    @property
    def key(self):
        """ Get ID assigned to the asset """
        return self.state.key

    @property
    def state(self):
        """State manager instance"""
        return self._state

    @property
    def power_on_when_ac_restore(self):
        """Indicates if asset should power up when input power is present"""
        return True

    @property
    def state_reason(self):
        """Reason for asset power state"""
        return self._state_reason

    @state_reason.setter
    def state_reason(self, value):
        self._state_reason = value

    @property
    def power_state_caused_by_user(self):
        """Returns true if user powered down/up the asset (and not AC power event)"""
        return (
            self.state_reason == asset_events.ButtonPowerDownPressed
            or self.state_reason == asset_events.ButtonPowerUpPressed
        )

    def power_up(self):
        """Power up this asset 
        Returns: 
            PowerEventResult: tuple indicating asset key, type, old & new states
        """
        old_state = self.state.status
        return event_results.PowerEventResult(
            asset_key=self.state.key,
            asset_type=self.state.asset_type,
            old_state=old_state,
            load_change=0,
            new_state=self.state.power_up(),
        )

    def shut_down(self):
        """Shut down this asset 
        Returns: 
            PowerEventResult: tuple indicating asset key, type, old & new states
        """
        old_state = self.state.status
        return event_results.PowerEventResult(
            asset_key=self.state.key,
            asset_type=self.state.asset_type,
            old_state=old_state,
            load_change=0,
            new_state=self.state.shut_down(),
        )

    def power_off(self):
        """Power down this asset 
        Returns: 
            PowerEventResult: tuple indicating asset key, type, old & new states
        """
        old_state = self.state.status
        return event_results.PowerEventResult(
            asset_key=self.state.key,
            asset_type=self.state.asset_type,
            old_state=old_state,
            new_state=self.state.power_off(),
        )

    def _update_load(self, load_change, arithmetic_op):
        """React to load changes by updating asset load
        
        Args:
            load_change(float): how much AMPs need to be added/subtracted
            arithmetic_op(callable): calculates new load
                                     (receives old load & measured load change)
            msg(str): message to be printed
        
        Returns:
            LoadEventResult: Event result containing old 
                             & new load values as well as value subtracted/added
        """

        old_load = self.state.load
        new_load = arithmetic_op(old_load, load_change)

        self.state.update_load(new_load)

        return event_results.LoadEventResult(
            old_load=old_load, new_load=new_load, asset_key=self.state.key
        )

    @handler("ChildAssetLoadIncreased", "ChildAssetPowerUp")
    def on_load_increase(self, event, *args, **kwargs):
        """Load is ramped up if child is powered up or child asset's load is increased
        Returns: 
            LoadEventResult: details on the asset state updates
        """

        increased_by = kwargs["child_load"]
        return self._update_load(increased_by, lambda old, change: old + change)

    @handler("ChildAssetLoadDecreased", "ChildAssetPowerDown")
    def on_load_decrease(self, event, *args, **kwargs):
        """Load is decreased if child is powered off or child asset's load is decreased
        Returns: 
            LoadEventResult: details on the asset state updates
        """

        decreased_by = kwargs["child_load"]
        return self._update_load(decreased_by, lambda old, change: old - change)

    @handler("ChildLoadUpEvent", "ChildLoadDownEvent")
    def on_child_load_update(self, event, *args, **kwargs):
        asset_load_event = event.get_next_load_event(self)
        new_load = asset_load_event.load.old + event.load.difference

        self.state.update_load(new_load)
        asset_load_event.load.new = new_load
        return asset_load_event

    @handler("ButtonPowerDownPressed")
    def on_btn_power_down(self, event):
        """When user presses power button to turn asset off"""
        self.state_reason = asset_events.ButtonPowerDownPressed

    @handler("ButtonPowerUpPressed")
    def on_btn_power_up(self, event):
        """When user preses power button to turn asset on"""
        self.state_reason = asset_events.ButtonPowerUpPressed

    def _process_parent_volt_e(self, event):
        """Process parent voltage event by analyzing if voltage is 
        within the accepted threshold and if asset power state 
        needs to be changed"""

        calc_load = lambda v: self.state.power_consumption / v if v else 0

        asset_event = event.get_next_power_event(self)
        asset_event.state.old = self.state.status

        min_voltage = self.state.min_voltage_prop()
        power_action = None

        old_out_volt, new_out_volt = asset_event.out_volt.old, asset_event.out_volt.new

        # Asset is underpowered (volt is too low)
        if new_out_volt <= min_voltage and asset_event.state.old:
            power_action = self.state.power_off
        # Asset was offline and underpowered, power back up
        elif new_out_volt > min_voltage and not asset_event.state.old:
            power_action = self.state.power_up

        # re-set output voltage values in case of power condition
        if power_action:
            # TODO: should call asset implementations
            # (on_power_up_request_received/on_power_off_request_received)
            asset_event.state.new = power_action()
            asset_event.out_volt.old = old_out_volt * asset_event.state.old
            asset_event.out_volt.new = new_out_volt * (int(old_out_volt) ^ 1)

        old_load, new_load = (
            calc_load(volt)
            for volt in [asset_event.out_volt.old, asset_event.out_volt.new]
        )

        asset_event.load.new = new_load
        asset_event.load.old = old_load
        if new_load != old_load:
            self.state.update_load(self.state.load - old_load + new_load)

        return asset_event

    @handler("InputVoltageUpEvent", "InputVoltageDownEvent", priority=-1)
    def detect_input_voltage(self, event, *args, **kwargs):
        """Update input voltage"""
        self.state.update_input_voltage(kwargs["new_in_volt"])
        print(
            "VOLTAGE {} {}, in[{}]".format(
                event.name, self.key, self.state.input_voltage
            )
        )

    @handler("InputVoltageUpEvent")
    def on_parent_volt_up(self, event, *args, **kwargs):
        """React to input voltage spike;
        Asset can power up on volt increase if it was down;
        """
        return self._process_parent_volt_e(event)

    @handler("InputVoltageDownEvent")
    def on_parent_volt_down(self, event, *args, **kwargs):
        """React to input voltage drop;
        Asset can power off if input voltage drops below the acceptable
        threshold"""
        return self._process_parent_volt_e(event)

    def on_power_up_request_received(self, event, *args, **kwargs):
        """Called on voltage spike"""
        raise NotImplementedError

    def on_power_off_request_received(self, event, *args, **kwargs):
        """Called on voltage drop"""
        raise NotImplementedError

    @classmethod
    def get_supported_assets(cls):
        """Get factory containing registered assets"""
        return SUPPORTED_ASSETS
