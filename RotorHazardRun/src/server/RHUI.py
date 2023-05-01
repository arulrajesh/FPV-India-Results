#
# RHUI Helper
# Provides abstraction for user interface
#
from dataclasses import dataclass
from flask import request
from flask_socketio import emit
from eventmanager import Evt
import json
import subprocess
from collections import OrderedDict
import gevent
import RHUtils
from RHUtils import catchLogExceptionsWrapper
from Database import ProgramMethod
import logging
logger = logging.getLogger(__name__)

# Language placeholder (Overwritten after module init)
def __(*args):
    return args

class RHUI():
    def __init__(self, APP, SOCKET_IO, RaceContext, Events):
        self._app = APP
        self._socket = SOCKET_IO
        self._racecontext = RaceContext
        self._events = Events

        self._pilot_attributes = []
        self._ui_panels = []
        self._general_settings = []

    # Pilot Attributes
    def register_pilot_attribute(self, name, label, fieldtype="text"):
        # TODO: prevent duplicate attributes
        self._pilot_attributes.append(PilotAttribute(name, label, fieldtype))
        return self._pilot_attributes

    @property
    def pilot_attributes(self):
        return self._pilot_attributes

    # UI Panels
    def register_ui_panel(self, name, label, page, order=0):
        # TODO: prevent duplicate panels
        self.ui_panels.append(UIPanel(name, label, page, order))
        return self.ui_panels

    @property
    def ui_panels(self):
        return self._ui_panels

    # General Settings
    def register_general_setting(self, name, label, panel=None, fieldtype="text", order=0):
        # TODO: prevent duplicate settings
        self._general_settings.append(GeneralSetting(name, label, panel, fieldtype, order))
        return self._general_settings

    @property
    def general_settings(self):
        return self._general_settings

    def get_panel_settings(self, name):
        payload = []
        for setting in self.general_settings:
            if setting.panel == name:
                payload.append(setting)
        return payload

    # General Emits
    def emit_frontend_load(self, **params):
        '''Emits reload command.'''
        if ('nobroadcast' in params):
            emit('load_all')
        else:
            self._socket.emit('load_all')

    def emit_ui(self, page, **params):
        '''Emits UI objects'''

        emit_payload = []

        for panel in self.ui_panels:
            if panel.page == page:
                settings = []
                for setting in self.get_panel_settings(panel.name):
                    settings.append({
                        'name': setting.name,
                        'label': setting.label,
                        'order': setting.order,
                        'fieldtype': setting.fieldtype,
                        'value': self._racecontext.rhdata.get_option(setting.name, None)
                    })

                emit_payload.append({
                    'panel': {
                        'name': panel.name,
                        'label': panel.label,
                        'order': panel.order,
                    },
                    'settings': settings
                })

        if ('nobroadcast' in params):
            emit('ui', emit_payload)
        else:
            self._socket.emit('ui', emit_payload)

    def emit_priority_message(self, message, interrupt=False, caller=False, **params):
        ''' Emits message to all clients '''
        emit_payload = {
            'message': message,
            'interrupt': interrupt
        }
        if ('nobroadcast' in params):
            emit('priority_message', emit_payload)
        else:
            if interrupt:
                self._events.trigger(Evt.MESSAGE_INTERRUPT, {
                    'message': message,
                    'interrupt': interrupt,
                    'caller': caller
                    })
            else:
                self._events.trigger(Evt.MESSAGE_STANDARD, {
                    'message': message,
                    'interrupt': interrupt,
                    'caller': caller
                    })

            self._socket.emit('priority_message', emit_payload)

    def emit_race_status(self, **params):
        '''Emits race status.'''
        race_format = self._racecontext.race.format

        emit_payload = {
                'race_status': self._racecontext.race.race_status,
                'race_format_id': self._racecontext.race.format.id if hasattr(self._racecontext.race.format, 'id') else None,
                'race_mode': race_format.race_mode,
                'race_time_sec': race_format.race_time_sec,
                'race_staging_tones': race_format.staging_tones,
                'hide_stage_timer': race_format.start_delay_min_ms != race_format.start_delay_max_ms,
                'pi_starts_at_s': self._racecontext.race.start_time_monotonic,
                'pi_staging_at_s': self._racecontext.race.stage_time_monotonic,
            }
        if ('nobroadcast' in params):
            emit('race_status', emit_payload)
        else:
            self._socket.emit('race_status', emit_payload)

    def emit_frequency_data(self, **params):
        '''Emits node data.'''
        profile_freqs = json.loads(self._racecontext.race.profile.frequencies)

        fdata = []
        for idx in range(self._racecontext.race.num_nodes):
            fdata.append({
                    'band': profile_freqs["b"][idx],
                    'channel': profile_freqs["c"][idx],
                    'frequency': profile_freqs["f"][idx]
                })

        emit_payload = {
                'fdata': fdata
            }

        if ('nobroadcast' in params):
            emit('frequency_data', emit_payload)
        else:
            self._socket.emit('frequency_data', emit_payload)

            # send changes to LiveTime
            for n in range(self._racecontext.race.num_nodes):
                # if session.get('LiveTime', False):
                self._socket.emit('frequency_set', {
                    'node': n,
                    'frequency': profile_freqs["f"][n]
                })

    def emit_node_data(self, **params):
        '''Emits node data.'''
        emit_payload = {
                'node_peak_rssi': [node.node_peak_rssi for node in self._racecontext.interface.nodes],
                'node_nadir_rssi': [node.node_nadir_rssi for node in self._racecontext.interface.nodes],
                'pass_peak_rssi': [node.pass_peak_rssi for node in self._racecontext.interface.nodes],
                'pass_nadir_rssi': [node.pass_nadir_rssi for node in self._racecontext.interface.nodes],
                'debug_pass_count': [node.debug_pass_count for node in self._racecontext.interface.nodes]
            }
        if ('nobroadcast' in params):
            emit('node_data', emit_payload)
        else:
            self._socket.emit('node_data', emit_payload)

    def emit_environmental_data(self, **params):
        '''Emits environmental data.'''
        emit_payload = []
        for sensor in self._racecontext.sensors:
            emit_payload.append({sensor.name: sensor.getReadings()})

        if ('nobroadcast' in params):
            emit('environmental_data', emit_payload)
        else:
            self._socket.emit('environmental_data', emit_payload)

    def emit_enter_and_exit_at_levels(self, **params):
        '''Emits enter-at and exit-at levels for nodes.'''
        profile = self._racecontext.race.profile
        profile_enter_ats = json.loads(profile.enter_ats)
        profile_exit_ats = json.loads(profile.exit_ats)

        emit_payload = {
            'enter_at_levels': profile_enter_ats["v"][:self._racecontext.race.num_nodes],
            'exit_at_levels': profile_exit_ats["v"][:self._racecontext.race.num_nodes]
        }
        if ('nobroadcast' in params):
            emit('enter_and_exit_at_levels', emit_payload)
        else:
            self._socket.emit('enter_and_exit_at_levels', emit_payload)

    def emit_cluster_status(self, **params):
        '''Emits cluster status information.'''
        if self._racecontext.cluster:
            if ('nobroadcast' in params):
                emit('cluster_status', self._racecontext.cluster.getClusterStatusInfo())
            else:
                self._socket.emit('cluster_status', self._racecontext.cluster.getClusterStatusInfo())

    def emit_start_thresh_lower_amount(self, **params):
        '''Emits current start_thresh_lower_amount.'''
        emit_payload = {
            'start_thresh_lower_amount': self._racecontext.rhdata.get_optionInt('startThreshLowerAmount'),
        }
        if ('nobroadcast' in params):
            emit('start_thresh_lower_amount', emit_payload)
        else:
            self._socket.emit('start_thresh_lower_amount', emit_payload)

    def emit_start_thresh_lower_duration(self, **params):
        '''Emits current start_thresh_lower_duration.'''
        emit_payload = {
            'start_thresh_lower_duration': self._racecontext.rhdata.get_optionInt('startThreshLowerDuration'),
        }
        if ('nobroadcast' in params):
            emit('start_thresh_lower_duration', emit_payload)
        else:
            self._socket.emit('start_thresh_lower_duration', emit_payload)

    def emit_node_tuning(self, **params):
        '''Emits node tuning values.'''
        tune_val = self._racecontext.race.profile
        emit_payload = {
            'profile_ids': [profile.id for profile in self._racecontext.rhdata.get_profiles()],
            'profile_names': [profile.name for profile in self._racecontext.rhdata.get_profiles()],
            'current_profile': self._racecontext.rhdata.get_optionInt('currentProfile'),
            'profile_name': tune_val.name,
            'profile_description': tune_val.description
        }
        if ('nobroadcast' in params):
            emit('node_tuning', emit_payload)
        else:
            self._socket.emit('node_tuning', emit_payload)

    def emit_language(self, **params):
        '''Emits race status.'''
        emit_payload = {
                'language': self._racecontext.rhdata.get_option("currentLanguage"),
                'languages': self._racecontext.language.getLanguages()
            }
        if ('nobroadcast' in params):
            emit('language', emit_payload)
        else:
            self._socket.emit('language', emit_payload)

    def emit_all_languages(self, **params):
        '''Emits full language dictionary.'''
        emit_payload = {
                'languages': self._racecontext.language.getAllLanguages()
            }
        if ('nobroadcast' in params):
            emit('all_languages', emit_payload)
        else:
            self._socket.emit('all_languages', emit_payload)

    def emit_action_setup(self, EventActionsObj, **params):
        '''Emits events and effects for actions.'''
        emit_payload = {
            'enabled': False
        }

        if EventActionsObj:
            effects = EventActionsObj.getRegisteredEffects()

            if effects:
                effect_list = {}
                for effect in effects:
                    effect_list[effect] = {
                        'name': __(effects[effect].label),
                        'fields': effects[effect].fields
                    }

                emit_payload = {
                    'enabled': True,
                    'events': None,
                    'effects': effect_list,
                }

        if ('nobroadcast' in params):
            emit('action_setup', emit_payload)
        else:
            self._socket.emit('action_setup', emit_payload)

    def emit_event_actions(self, **params):
        '''Emits event actions.'''
        emit_payload = {
            'actions': self._racecontext.rhdata.get_option('actions'),
        }
        if ('nobroadcast' in params):
            emit('event_actions', emit_payload)
        else:
            self._socket.emit('event_actions', emit_payload)

    def emit_min_lap(self, **params):
        '''Emits current minimum lap.'''
        emit_payload = {
            'min_lap': self._racecontext.rhdata.get_optionInt('MinLapSec'),
            'min_lap_behavior': self._racecontext.rhdata.get_optionInt("MinLapBehavior")
        }
        if ('nobroadcast' in params):
            emit('min_lap', emit_payload)
        else:
            self._socket.emit('min_lap', emit_payload)

    def emit_current_laps(self, **params):
        '''Emits current laps.'''
        emit_payload = {
            'current': {}
        }
        emit_payload['current'] = self._racecontext.race.get_lap_results()

        if self._racecontext.last_race is not None:
            emit_payload['last_race'] = self._racecontext.last_race.get_lap_results()

        if ('nobroadcast' in params):
            emit('current_laps', emit_payload)
        else:
            self._socket.emit('current_laps', emit_payload)

    def emit_race_list(self, **params):
        '''Emits race listing'''
        heats = {}
        for heat in self._racecontext.rhdata.get_heats():
            if self._racecontext.rhdata.savedRaceMetas_has_heat(heat.id):
                rounds = {}
                for race in self._racecontext.rhdata.get_savedRaceMetas_by_heat(heat.id):
                    pilotraces = []
                    for pilotrace in self._racecontext.rhdata.get_savedPilotRaces_by_savedRaceMeta(race.id):
                        pilot_data = self._racecontext.rhdata.get_pilot(pilotrace.pilot_id)
                        if pilot_data:
                            nodepilot = pilot_data.callsign
                        else:
                            nodepilot = None

                        pilotraces.append({
                            'pilotrace_id': pilotrace.id,
                            'callsign': nodepilot,
                            'pilot_id': pilotrace.pilot_id,
                            'node_index': pilotrace.node_index,
                        })
                    rounds[race.round_id] = {
                        'race_id': race.id,
                        'class_id': race.class_id,
                        'format_id': race.format_id,
                        'start_time': race.start_time,
                        'start_time_formatted': race.start_time_formatted,
                        'pilotraces': pilotraces
                    }
                heats[heat.id] = {
                    'heat_id': heat.id,
                    'displayname': heat.displayname(),
                    'rounds': rounds,
                }

        emit_payload = {
            'heats': heats,
            # 'heats_by_class': heats_by_class,
            # 'classes': current_classes,
        }

        if ('nobroadcast' in params):
            emit('race_list', emit_payload)
        else:
            self._socket.emit('race_list', emit_payload)

    def emit_result_data(self, **params):
        ''' kick off non-blocking thread to generate data'''
        if request:
            gevent.spawn(self.emit_result_data_thread, params, request.sid)
        else:
            gevent.spawn(self.emit_result_data_thread, params)

    @catchLogExceptionsWrapper
    def emit_result_data_thread(self, params, sid=None):
        with self._app.test_request_context():

            emit_payload = self._racecontext.pagecache.get_cache()

            if 'nobroadcast' in params and sid != None:
                emit('result_data', emit_payload, namespace='/', room=sid)
            else:
                self._socket.emit('result_data', emit_payload, namespace='/')

    def emit_current_leaderboard(self, **params):
        '''Emits leaderboard.'''

        emit_payload = {
            'current': {}
        }

        if self._racecontext.race.current_heat is RHUtils.HEAT_ID_NONE:
            emit_payload['current']['displayname'] = __("Practice")
        else:
            emit_payload['current']['displayname'] = self._racecontext.rhdata.get_heat(self._racecontext.race.current_heat).displayname()

        # current
        if self._racecontext.race.current_heat is RHUtils.HEAT_ID_NONE:
            emit_payload['current']['displayname'] = __("Practice")
        else:
            emit_payload['current']['displayname'] = self._racecontext.rhdata.get_heat(self._racecontext.race.current_heat).displayname()

        emit_payload['current']['heat'] = self._racecontext.race.current_heat
        emit_payload['current']['status_msg'] = self._racecontext.race.status_message

        emit_payload['current']['leaderboard'] = self._racecontext.race.get_results()

        if self._racecontext.race.format.team_racing_mode:
            emit_payload['current']['team_leaderboard'] = self._racecontext.race.get_team_results(self._racecontext.rhdata)

        # cache
        if self._racecontext.last_race is not None:
            emit_payload['last_race'] = {}

            if self._racecontext.last_race.current_heat is RHUtils.HEAT_ID_NONE:
                emit_payload['last_race']['displayname'] = __("Practice")
            else:
                if (self._racecontext.last_race):
                    heat = self._racecontext.rhdata.get_heat(self._racecontext.last_race.current_heat)
                    if heat:
                        emit_payload['last_race']['displayname'] = self._racecontext.rhdata.get_heat(self._racecontext.last_race.current_heat).displayname()

            emit_payload['last_race']['heat'] = self._racecontext.last_race.current_heat
            emit_payload['last_race']['status_msg'] = self._racecontext.last_race.status_message

            emit_payload['last_race']['leaderboard'] = self._racecontext.last_race.get_results()

            if self._racecontext.last_race.format.team_racing_mode:
                emit_payload['last_race']['team_leaderboard'] = self._racecontext.last_race.get_team_results(self._racecontext.rhdata)

        if ('nobroadcast' in params):
            emit('leaderboard', emit_payload)
        else:
            self._socket.emit('leaderboard', emit_payload)

    def emit_heat_data(self, **params):
        '''Emits heat data.'''

        heats = []
        for heat in self._racecontext.rhdata.get_heats():
            current_heat = {}
            current_heat['id'] = heat.id
            current_heat['note'] = heat.note
            current_heat['displayname'] = heat.displayname()
            current_heat['class_id'] = heat.class_id
            current_heat['order'] = heat.order
            current_heat['status'] = heat.status
            current_heat['auto_frequency'] = heat.auto_frequency

            current_heat['slots'] = []

            heatNodes = self._racecontext.rhdata.get_heatNodes_by_heat(heat.id)
            def heatNodeSorter(x):
                if not x.node_index:
                    return -1
                return x.node_index
            heatNodes.sort(key=heatNodeSorter)

            is_dynamic = False
            for heatNode in heatNodes:
                current_node = {}
                current_node['id'] = heatNode.id
                current_node['node_index'] = heatNode.node_index
                current_node['pilot_id'] = heatNode.pilot_id
                current_node['color'] = heatNode.color
                current_node['method'] = heatNode.method
                current_node['seed_rank'] = heatNode.seed_rank
                current_node['seed_id'] = heatNode.seed_id
                current_heat['slots'].append(current_node)

                if current_node['method'] == ProgramMethod.HEAT_RESULT or current_node['method'] == ProgramMethod.CLASS_RESULT:
                    is_dynamic = True

            current_heat['dynamic'] = is_dynamic

            current_heat['locked'] = bool(self._racecontext.rhdata.savedRaceMetas_has_heat(heat.id))
            heats.append(current_heat)

        emit_payload = {
            'heats': heats,
        }
        if ('nobroadcast' in params):
            emit('heat_data', emit_payload)
        elif ('noself' in params):
            emit('heat_data', emit_payload, broadcast=True, include_self=False)
        else:
            self._socket.emit('heat_data', emit_payload)

    def emit_class_data(self, **params):
        '''Emits class data.'''
        current_classes = []
        for race_class in self._racecontext.rhdata.get_raceClasses():
            current_class = {}
            current_class['id'] = race_class.id
            current_class['name'] = race_class.name
            current_class['displayname'] = race_class.displayname()
            current_class['description'] = race_class.description
            current_class['format'] = race_class.format_id
            current_class['win_condition'] = race_class.win_condition
            current_class['rounds'] = race_class.rounds
            current_class['heat_advance'] = race_class.heatAdvanceType
            current_class['order'] = race_class.order
            current_class['locked'] = self._racecontext.rhdata.savedRaceMetas_has_raceClass(race_class.id)
            current_classes.append(current_class)

        emit_payload = {
            'classes': current_classes,
        }
        if ('nobroadcast' in params):
            emit('class_data', emit_payload)
        elif ('noself' in params):
            emit('class_data', emit_payload, broadcast=True, include_self=False)
        else:
            self._socket.emit('class_data', emit_payload)

    def emit_format_data(self, **params):
        '''Emits format data.'''
        formats = []
        for race_format in self._racecontext.rhdata.get_raceFormats():
            raceformat = {}
            raceformat['id'] = race_format.id
            raceformat['name'] = race_format.name
            raceformat['race_mode'] = race_format.race_mode
            raceformat['race_time_sec'] = race_format.race_time_sec
            raceformat['lap_grace_sec'] = race_format.lap_grace_sec
            raceformat['staging_fixed_tones'] = race_format.staging_fixed_tones
            raceformat['staging_tones'] = race_format.staging_tones
            raceformat['start_delay_min'] = race_format.start_delay_min_ms
            raceformat['start_delay_max'] = race_format.start_delay_max_ms
            raceformat['number_laps_win'] = race_format.number_laps_win
            raceformat['win_condition'] = race_format.win_condition
            raceformat['team_racing_mode'] = 1 if race_format.team_racing_mode else 0
            raceformat['start_behavior'] = race_format.start_behavior
            raceformat['locked'] = self._racecontext.rhdata.savedRaceMetas_has_raceFormat(race_format.id)
            formats.append(raceformat)

        emit_payload = {
            'formats': formats,
        }
        if ('nobroadcast' in params):
            emit('format_data', emit_payload)
        elif ('noself' in params):
            emit('format_data', emit_payload, broadcast=True, include_self=False)
        else:
            self._socket.emit('format_data', emit_payload)

    def emit_pilot_data(self, **params):
        '''Emits pilot data.'''
        pilots_list = []

        attrs = []
        for attr in self.pilot_attributes:
            attrs.append({
                'name': attr.name,
                'label': attr.label,
                'fieldtype': attr.fieldtype
            })

        for pilot in self._racecontext.rhdata.get_pilots():
            opts_str = '' # create team-options string for each pilot, with current team selected
            for name in self._racecontext.rhdata.TEAM_NAMES_LIST:
                opts_str += '<option value="' + name + '"'
                if name == pilot.team:
                    opts_str += ' selected'
                opts_str += '>' + name + '</option>'

            locked = self._racecontext.rhdata.savedPilotRaces_has_pilot(pilot.id)

            pilot_data = {
                'pilot_id': pilot.id,
                'callsign': pilot.callsign,
                'team': pilot.team,
                'phonetic': pilot.phonetic,
                'name': pilot.name,
                'active': pilot.active,
                'team_options': opts_str,
                'locked': locked,
            }

            pilot_attributes = self._racecontext.rhdata.get_pilot_attributes(pilot)
            for attr in pilot_attributes: 
                pilot_data[attr.name] = attr.value

            if self._racecontext.led_manager.isEnabled():
                pilot_data['color'] = pilot.color

            pilots_list.append(pilot_data)

            if self._racecontext.rhdata.get_option('pilotSort') == 'callsign':
                pilots_list.sort(key=lambda x: (x['callsign'], x['name']))
            else:
                pilots_list.sort(key=lambda x: (x['name'], x['callsign']))

        emit_payload = {
            'pilots': pilots_list,
            'pilotSort': self._racecontext.rhdata.get_option('pilotSort'),
            'attributes': attrs
        }
        if ('nobroadcast' in params):
            emit('pilot_data', emit_payload)
        elif ('noself' in params):
            emit('pilot_data', emit_payload, broadcast=True, include_self=False)
        else:
            self._socket.emit('pilot_data', emit_payload)

        self.emit_heat_data()

    def emit_current_heat(self, **params):
        '''Emits the current heat.'''
        heat_data = self._racecontext.rhdata.get_heat(self._racecontext.race.current_heat)

        heatNode_data = {}
        for idx in range(self._racecontext.race.num_nodes):
            heatNode_data[idx] = {
                'pilot_id': None,
                'callsign': None,
                'heatNodeColor': None,
                'pilotColor': None,
                'activeColor': None
            }

        heat_format = None

        if (heat_data):
            heat_class = heat_data.class_id

            for heatNode in self._racecontext.rhdata.get_heatNodes_by_heat(self._racecontext.race.current_heat):
                if heatNode.node_index is not None:
                    heatNode_data[heatNode.node_index] = {
                        'pilot_id': heatNode.pilot_id,
                        'callsign': None,
                        'heatNodeColor': heatNode.color,
                        'pilotColor': None,
                        'activeColor': None
                        }
                    pilot = self._racecontext.rhdata.get_pilot(heatNode.pilot_id)
                    if pilot:
                        heatNode_data[heatNode.node_index]['callsign'] = pilot.callsign
                        heatNode_data[heatNode.node_index]['pilotColor'] = pilot.color

                    if self._racecontext.led_manager.isEnabled():
                        heatNode_data[heatNode.node_index]['activeColor'] = self._racecontext.led_manager.getDisplayColor(heatNode.node_index)

            if heat_data.class_id != RHUtils.CLASS_ID_NONE:
                heat_format = self._racecontext.rhdata.get_raceClass(heat_data.class_id).format_id

        else:
            # Practice mode
            heat_class = RHUtils.CLASS_ID_NONE

            profile_freqs = json.loads(self._racecontext.race.profile.frequencies)

            for idx in range(self._racecontext.race.num_nodes):
                if (profile_freqs["b"][idx] and profile_freqs["c"][idx]):
                    callsign = profile_freqs["b"][idx] + str(profile_freqs["c"][idx])
                else:
                    callsign = str(profile_freqs["f"][idx])

                heatNode_data[idx] = {
                    'callsign': callsign,
                    'heatNodeColor': None,
                    'pilotColor': None,
                    'activeColor': self._racecontext.led_manager.getDisplayColor(idx)
                }

        emit_payload = {
            'current_heat': self._racecontext.race.current_heat,
            'heatNodes': heatNode_data,
            'heat_format': heat_format,
            'heat_class': heat_class
        }
        if ('nobroadcast' in params):
            emit('current_heat', emit_payload)
        else:
            self._socket.emit('current_heat', emit_payload)

    def emit_phonetic_data(self, pilot_id, lap_id, lap_time, team_name, team_laps, leader_flag=False, node_finished=False, node_index=None, **params):
        '''Emits phonetic data.'''
        raw_time = lap_time
        phonetic_time = RHUtils.phonetictime_format(lap_time, self._racecontext.rhdata.get_option('timeFormatPhonetic'))

        emit_payload = {
            'lap': lap_id,
            'raw_time': raw_time,
            'phonetic': phonetic_time,
            'team_name' : team_name,
            'team_laps' : team_laps,
            'leader_flag' : leader_flag,
            'node_finished': node_finished,
        }

        pilot = self._racecontext.rhdata.get_pilot(pilot_id)
        if pilot:
            emit_payload['pilot'] = pilot.phonetic
            emit_payload['callsign'] = pilot.callsign
            emit_payload['pilot_id'] = pilot.id
        elif node_index is not None:
            profile_freqs = json.loads(self._racecontext.race.profile.frequencies)

            if (profile_freqs["b"][node_index] and profile_freqs["c"][node_index]):
                callsign = profile_freqs["b"][node_index] + str(profile_freqs["c"][node_index])
            else:
                callsign = str(profile_freqs["f"][node_index])

            emit_payload['pilot'] = callsign
            emit_payload['callsign'] = callsign
            emit_payload['pilot_id'] = None
        else:
            emit_payload['pilot'] = None
            emit_payload['callsign'] = None
            emit_payload['pilot_id'] = None

        if ('nobroadcast' in params):
            emit('phonetic_data', emit_payload)
        else:
            self._socket.emit('phonetic_data', emit_payload)

    def emit_first_pass_registered(self, node_idx, **params):
        '''Emits when first pass (lap 0) is registered during a race'''
        emit_payload = {
            'node_index': node_idx,
        }
        self._events.trigger(Evt.RACE_FIRST_PASS, {
            'node_index': node_idx,
            })

        if ('nobroadcast' in params):
            emit('first_pass_registered', emit_payload)
        else:
            self._socket.emit('first_pass_registered', emit_payload)

    def emit_phonetic_text(self, text_str, domain=False, winner_flag=False, **params):
        '''Emits given phonetic text.'''
        emit_payload = {
            'text': text_str,
            'domain': domain,
            'winner_flag': winner_flag
        }
        if ('nobroadcast' in params):
            emit('phonetic_text', emit_payload)
        else:
            self._socket.emit('phonetic_text', emit_payload)

    def emit_phonetic_split(self, pilot_id, split_id, split_time, **params):
        '''Emits phonetic split-pass data.'''
        pilot = self._racecontext.rhdata.get_pilot(pilot_id)
        phonetic_name = pilot.phonetic or pilot.callsign
        phonetic_time = RHUtils.phonetictime_format(split_time, self._racecontext.rhdata.get_option('timeFormatPhonetic'))
        emit_payload = {
            'pilot_name': phonetic_name,
            'split_id': str(split_id+1),
            'split_time': phonetic_time
        }
        if ('nobroadcast' in params):
            emit('phonetic_split_call', emit_payload)
        else:
            self._socket.emit('phonetic_split_call', emit_payload)

    def emit_split_pass_info(self, pilot_id, split_id, split_time):
        self.emit_current_laps()  # update all laps on the race page
        self.emit_phonetic_split(pilot_id, split_id, split_time)

    def emit_enter_at_level(self, node, **params):
        '''Emits enter-at level for given node.'''
        emit_payload = {
            'node_index': node.index,
            'level': node.enter_at_level
        }
        if ('nobroadcast' in params):
            emit('node_enter_at_level', emit_payload)
        else:
            self._socket.emit('node_enter_at_level', emit_payload)

    def emit_exit_at_level(self, node, **params):
        '''Emits exit-at level for given node.'''
        emit_payload = {
            'node_index': node.index,
            'level': node.exit_at_level
        }
        if ('nobroadcast' in params):
            emit('node_exit_at_level', emit_payload)
        else:
            self._socket.emit('node_exit_at_level', emit_payload)

    def emit_node_crossing_change(self, node, **params):
        '''Emits crossing-flag change for given node.'''
        emit_payload = {
            'node_index': node.index,
            'crossing_flag': node.crossing_flag
        }
        if ('nobroadcast' in params):
            emit('node_crossing_change', emit_payload)
        else:
            self._socket.emit('node_crossing_change', emit_payload)

    def emit_cluster_connect_change(self, connect_flag, **params):
        '''Emits connect/disconnect tone for cluster timer.'''
        emit_payload = {
            'connect_flag': connect_flag
        }
        if ('nobroadcast' in params):
            emit('cluster_connect_change', emit_payload)
        else:
            self._socket.emit('cluster_connect_change', emit_payload)

    def emit_callouts(self):
        callouts = self._racecontext.rhdata.get_option('voiceCallouts')
        if callouts:
            emit('callouts', json.loads(callouts))

    def emit_imdtabler_page(self, IMDTABLER_JAR_NAME, Use_imdtabler_jar_flag, **_params):
        '''Emits IMDTabler page, using current profile frequencies.'''
        if Use_imdtabler_jar_flag:
            try:                          # get IMDTabler version string
                imdtabler_ver = subprocess.check_output( \
                                    'java -jar ' + IMDTABLER_JAR_NAME + ' -v', shell=True).decode("utf-8").rstrip()
                profile_freqs = json.loads(self._racecontext.race.profile.frequencies)
                fi_list = list(OrderedDict.fromkeys(profile_freqs['f'][:self._racecontext.race.num_nodes]))  # remove duplicates
                fs_list = []
                for val in fi_list:  # convert list of integers to list of strings
                    if val > 0:      # drop any zero entries
                        fs_list.append(str(val))
                self.emit_imdtabler_data(IMDTABLER_JAR_NAME, fs_list, imdtabler_ver)
            except Exception:
                logger.exception('emit_imdtabler_page exception')

    def emit_imdtabler_data(self, IMDTABLER_JAR_NAME, fs_list, imdtabler_ver=None, **params):
        '''Emits IMDTabler data for given frequencies.'''
        try:
            imdtabler_data = None
            if len(fs_list) > 2:  # if 3+ then invoke jar; get response
                imdtabler_data = subprocess.check_output( \
                            'java -jar ' + IMDTABLER_JAR_NAME + ' -t ' + ' '.join(fs_list), shell=True).decode("utf-8")
        except Exception:
            imdtabler_data = None
            logger.exception('emit_imdtabler_data exception')
        emit_payload = {
            'freq_list': ' '.join(fs_list),
            'table_data': imdtabler_data,
            'version_str': imdtabler_ver
        }
        if ('nobroadcast' in params):
            emit('imdtabler_data', emit_payload)
        else:
            self._socket.emit('imdtabler_data', emit_payload)

    def emit_imdtabler_rating(self, IMDTABLER_JAR_NAME):
        '''Emits IMDTabler rating for current profile frequencies.'''
        try:
            profile_freqs = json.loads(self._racecontext.race.profile.frequencies)
            imd_val = None
            fi_list = list(OrderedDict.fromkeys(profile_freqs['f'][:self._racecontext.race.num_nodes]))  # remove duplicates
            fs_list = []
            for val in fi_list:  # convert list of integers to list of strings
                if val > 0:      # drop any zero entries
                    fs_list.append(str(val))
            if len(fs_list) > 2:
                imd_val = subprocess.check_output(  # invoke jar; get response
                            'java -jar ' + IMDTABLER_JAR_NAME + ' -r ' + ' '.join(fs_list), shell=True).decode("utf-8").rstrip()
        except Exception:
            imd_val = None
            logger.exception('emit_imdtabler_rating exception')
        emit_payload = {
                'imd_rating': imd_val
            }
        self._socket.emit('imdtabler_rating', emit_payload)

    @catchLogExceptionsWrapper
    def emit_pass_record(self, node, lap_time_stamp):
        '''Emits 'pass_record' message (will be consumed by primary timer in cluster, livetime, etc).'''
        payload = {
            'node': node.index,
            'frequency': node.frequency,
            'timestamp': lap_time_stamp + self._racecontext.race.start_time_epoch_ms
        }
        self._racecontext.cluster.emit_cluster_msg_to_primary(self._socket, 'pass_record', payload)

    def emit_vrx_list(self, *_args, **params):
        ''' get list of connected VRx devices '''
        if self._racecontext.vrx_manager.isEnabled():
            emit_payload = {
                'enabled': True,
                'controllers': self._racecontext.vrx_manager.getControllerStatus(),
                'devices': self._racecontext.vrx_manager.getAllDeviceStatus()
            }
        else:
            emit_payload = {
                'enabled': False,
                'controllers': None,
                'devices': None
            }

        if ('nobroadcast' in params):
            emit('vrx_list', emit_payload)
        else:
            self._socket.emit('vrx_list', emit_payload)

    def emit_exporter_list(self):
        '''List Database Exporters'''

        emit_payload = {
            'exporters': []
        }

        for name, exp in self._racecontext.export_manager.getExporters().items():
            emit_payload['exporters'].append({
                'name': name,
                'label': exp.label
            })

        emit('exporter_list', emit_payload)

    def emit_heatgenerator_list(self):
        '''List Heat Generators'''

        emit_payload = {
            'generators': []
        }

        for name, exp in self._racecontext.heat_generate_manager.getGenerators().items():
            emit_payload['generators'].append({
                'name': name,
                'label': exp.label
            })

        emit('heatgenerator_list', emit_payload)

@dataclass
class PilotAttribute():
    name: str
    label: str
    fieldtype: str = "text"

@dataclass
class UIPanel():
    name: str
    label: str
    page: str
    order: int = 0

@dataclass
class GeneralSetting():
    name: str
    label: str
    panel: str = None
    fieldtype: str = "text"
    order: int = 0
