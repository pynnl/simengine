
"""storcli64 emulator that provides CLI access to (virtual) storage
"""

import os
import logging
from distutils import dir_util

import json
import socket
import threading
import copy
from string import Template

from enginecore.model.graph_reference import GraphReference
from enginecore.model.query_helpers import to_camelcase


class StorCLIEmulator():
    """This component emulates storcli behaviour
    - runs a websocket server that listens to any incoming commands from a vm
    """

    pd_header = [
        "EID:Slt", "DID", "State", "DG", "Size", "Intf", "Med", "SED", "PI", "SeSz", "Model", "Sp", "Type"
    ]

    vd_header = ["DG/VD", "TYPE", "State", "Access", "Consist", "Cache", "Cac", "sCC", "Size", "Name"]

    topology_header = [
        "DG", # disk group idx
        "Arr", # array idx
        "Row",
        "EID:Slot", # enclosure device ID
        "DID",
        "Type",
        "State",
        "BT", # background task
        "Size",
        "PDC", # pd cache
        "PI", # protection info
        "SED", # self encrypting drive
        "DS3", # Dimmer Switch 3
        "FSpace", # free space present
        "TR" # transport ready
    ]

    def __init__(self, asset_key, server_dir, socket_port):
        
        self._graph_ref = GraphReference()
        self._server_key = asset_key
        
        with self._graph_ref.get_session() as session:
            self._storcli_details = GraphReference.get_storcli_details(session, asset_key)

        self._storcli_dir = os.path.join(server_dir, "storcli")

        os.makedirs(self._storcli_dir)
        dir_util.copy_tree(os.environ.get('SIMENGINE_STORCLI_TEMPL'), self._storcli_dir)

        self._socket_t = threading.Thread(
            target=self._listen_cmds,
            args=(socket_port,),
            name="storcli64:{}".format(asset_key)
        )

        self._socket_t.daemon = True
        self._socket_t.start()


    def _strcli_header(self, ctrl_num=0, status='Success'):
        """Reusable header for storcli output"""

        with open(os.path.join(self._storcli_dir, 'header')) as templ_h:
            options = {
                'cli_version': self._storcli_details['CLIVersion'],
                'op_sys': self._storcli_details['operatingSystem'],
                'status': status,
                'description': 'None',
                'controller_line': 'Controller = {}\n'.format(ctrl_num) if ctrl_num else ''
            }

            template = Template(templ_h.read())
            return template.substitute(options)


    def _strcli_ctrlcount(self):
        """Number of adapters per server """

        template_f_path = os.path.join(self._storcli_dir, 'adapter_count')
        with open(template_f_path) as templ_h, self._graph_ref.get_session() as session:

            options = {
                'header': self._strcli_header(),
                'ctrl_count': GraphReference.get_controller_count(session, self._server_key)
            }

            template = Template(templ_h.read())
            return template.substitute(options)


    def _strcli_ctrl_perf_mode(self, controller_num):
        """Current performance mode (hardcoded)"""
        with open(os.path.join(self._storcli_dir, 'performance_mode')) as templ_h:
         
            options = {
                'header': self._strcli_header(controller_num),
                'mode_num': 0,
                'mode_description': 'tuned to provide Best IOPS'
            }

            template = Template(templ_h.read())
            return template.substitute(options)


    def _strcli_ctrl_alarm_state(self, controller_num):
        """Get controller alarm state"""

        alarm_state_f_path = os.path.join(self._storcli_dir, 'alarm_state')
        with open(alarm_state_f_path) as templ_h, self._graph_ref.get_session() as session:
            
            ctrl_info = GraphReference.get_controller_details(session, self._server_key, controller_num)
            
            options = {
                'header': self._strcli_header(controller_num),
                'alarm_state': ctrl_info['alarmState']
            }

            template = Template(templ_h.read())
            return template.substitute(options)


    def _strcli_ctrl_bbu(self, controller_num):
        """Battery backup unit output for storcli"""

        with open(os.path.join(self._storcli_dir, 'bbu_data')) as templ_h:
         
            options = {
                'header': self._strcli_header(controller_num),
                'ctrl_num': controller_num,
                'status': 'Failed',
                'property': '-',
                'err_msg': 'use /cx/cv',
                'err_code': 255
            }

            template = Template(templ_h.read())
            return template.substitute(options)


    def _get_rate_prop(self, controller_num, rate_type):
        """Get controller rate property (rate type matches rate template file and the rate template value)"""

        rate_file = os.path.join(self._storcli_dir, rate_type)
        with open(rate_file) as templ_h, self._graph_ref.get_session() as session:
            
            ctrl_info = GraphReference.get_controller_details(session, self._server_key, controller_num)

            options = {}
            options['header'] = self._strcli_header(controller_num)
            options[rate_type] = ctrl_info[to_camelcase(rate_type)]

            template = Template(templ_h.read())
            return template.substitute(options)
        

    def _strcli_ctrl_info(self, controller_num):
        """Return aggregated information for a particular controller (show all)"""

        ctrl_info_f = os.path.join(self._storcli_dir, 'controller_info')
        ctrl_entry_f = os.path.join(self._storcli_dir, 'controller_entry')

        with open(ctrl_info_f) as info_h, open(ctrl_entry_f) as entry_h, self._graph_ref.get_session() as session:
            
            ctrl_info = GraphReference.get_controller_details(session, self._server_key, controller_num)

            ctrl_info_templ_keys = [
                'serial_number', 'model', 'serial_number', 'mfg_date',
                'SAS_address', 'PCI_address', 'rework_date',
                'memory_correctable_errors', 'memory_uncorrectable_errors',
                'rebuild_rate', 'pr_rate', 'bgi_rate', 'cc_rate'
            ]
            

            entry_options = {
                'controller_num': controller_num,
                'controller_date': '',
                'system_date': '',
                'status': 'Optimal',
            }

            for key in ctrl_info_templ_keys:
                entry_options[key] = ctrl_info[to_camelcase(key)]

            drives = GraphReference.get_all_drives(session, self._server_key, controller_num)
            topology = []

            ctrl_state = copy.deepcopy(self._storcli_details['stateConfig']['controller']['Optimal'])
            ctrl_state['memoryCorrectableErrors'] = ctrl_info['memoryCorrectableErrors']
            ctrl_state['memoryUncorrectableErrors'] = ctrl_info['memoryUncorrectableErrors']

            for i, v_drive in enumerate(drives['vd']):

                vd_state = self._storcli_details['stateConfig']['virtualDrive']['Optl']

                # Add Virtual Drive output
                v_drive['DG/VD'] = '0/' + str(i)
                v_drive['Size'] = str(v_drive['Size']) + ' GB'

                # Add physical drive output (do some formatting plus check pd states)
                for p_drive in v_drive['pd']:
                    vd_state['mediaErrorCount'] += p_drive['mediaErrorCount']
                    vd_state['otherErrorCount'] += p_drive['otherErrorCount']

                    if p_drive['State'] == 'Offln':
                        vd_state['numPdOffline'] += 1
                    
                v_drive['State'] = self._get_state_from_config('virtualDrive', vd_state, 'Optl')
                
                topology.append({
                    'DG': 0,
                    'Arr': '-',
                    'Row': '-',
                    'EID:Slot': '-',
                    'DID': '-',
                    'Type': v_drive['TYPE'],
                    'State': v_drive['State'],
                    'BT': 'N',
                    'Size': v_drive['Size'],
                    'PDC': 'disable',
                    'PI': 'N',
                    'SED': 'N',
                    'DS3': 'none',
                    'FSpace': 'N',
                    'TR': 'N'
                })

            # Add physical drive output (do some formatting plus check pd states)
            p_topology = []
            for p_drive in drives['pd']:
                p_drive['EID:Slt'] = '{}:{}'.format(p_drive['EID'], p_drive['slotNum'])
                p_drive['Size'] = str(p_drive['Size']) + ' GB'
                
                if p_drive['State'] == 'Offln':
                    ctrl_state['numPdOffline'] += 1

                p_topology.append({
                    'DG': 0,
                    'Arr': 0,
                    'Row': p_drive['slotNum'],
                    'EID:Slot': p_drive['EID:Slt'],
                    'DID': '-',
                    'Type': 'DRIVE',
                    'State': p_drive['State'],
                    'BT': 'N',
                    'Size': p_drive['Size'],
                    'PDC': 'disable',
                    'PI': 'N',
                    'SED': 'N',
                    'DS3': 'none',
                    'FSpace': 'N',
                    'TR': 'N'
                })


            topology.extend(sorted(p_topology, key=lambda k: k['Row']))
            entry_options['status'] = self._get_state_from_config('controller', ctrl_state, 'Optimal')
            
            # get cachevault details:
            cv_info = GraphReference.get_cachevault(session, self._server_key, controller_num)
            cv_table = {
                "Model": cv_info['model'],
                "State": cv_info['state'],
                "Temp": str(cv_info['temperature']) + "C",
                "Mode": "-",
                "MfgDate": cv_info['mfgDate']
            }


            info_options = {
                'header': self._strcli_header(controller_num),
                'controller_entry': Template(entry_h.read()).substitute(entry_options),
                'num_virt_drives': len(drives['vd']),
                'num_phys_drives': len(drives['pd']),
                'topology': self._format_as_table(StorCLIEmulator.topology_header, topology),
                'virtual_drives': self._format_as_table(StorCLIEmulator.vd_header, drives['vd']),
                'physical_drives': self._format_as_table(StorCLIEmulator.pd_header, drives['pd']),
                'cachevault': self._format_as_table(cv_table.keys(), [cv_table]) 
            }

            info_template = Template(info_h.read())
            return info_template.substitute(info_options)


    def _strcli_ctrl_cachevault(self, controller_num):
        """Cachevault output for storcli"""

        cv_f = os.path.join(self._storcli_dir, 'cachevault_data')
        with open(os.path.join(self._storcli_dir, cv_f)) as templ_h, self._graph_ref.get_session() as session:
         
            cv_info = GraphReference.get_cachevault(session, self._server_key, controller_num)
            cv_info['mfgDate'] = '/'.join(reversed(cv_info['mfgDate'].split('/'))) # dumb storcli (change date format)
            options = {
                **{'header': self._strcli_header(controller_num)},
                **cv_info
            }

            template = Template(templ_h.read())
            return template.substitute(options)


    def _strcli_ctrl_phys_disks(self, controller_num):
        """Storcli physical drive details"""

        pd_info_f = os.path.join(self._storcli_dir, 'physical_disk_data')
        pd_entry_f = os.path.join(self._storcli_dir, 'physical_disk_entry')
        pd_output = []

        info_options = {
            'header': self._strcli_header(controller_num),
            'physical_drives': ''
        }

        with open(pd_info_f) as info_h, open(pd_entry_f) as entry_h, self._graph_ref.get_session() as session:
            drives = GraphReference.get_all_drives(session, self._server_key, controller_num)
            pd_drives = sorted(drives['pd'], key=lambda k: k['slotNum'])
            pd_template = entry_h.read()

            for drive in pd_drives:

                drive['EID:Slt'] = '{}:{}'.format(drive['EID'], drive['slotNum'])
                drive['Size'] = str(drive['Size']) + ' GB'

                entry_options = {
                    'drive_path': '/c{}/e{}/s{}'.format(controller_num, drive['EID'], drive['slotNum']),
                    'drive_table': self._format_as_table(StorCLIEmulator.pd_header, [drive]),
                    'media_error_count': drive['mediaErrorCount'],
                    'other_error_count': drive['otherErrorCount'],
                    'predictive_failure_count': drive['predictiveErrorCount'],
                    'drive_temp_c': drive['temperature'],
                    'drive_temp_f': (drive['temperature'] * 9/5) + 32,
                    'drive_model': drive['Model'],
                    'drive_size': drive['Size']
                }

                pd_output.append(Template(pd_template).substitute(entry_options))


            info_options['physical_drives'] = '\n'.join(pd_output)
            return  Template(info_h.read()).substitute(info_options)


    def _format_as_table(self, headers, table_options):
        """Formats data as storcli table
        Args:
            headers(list): table header
            table_options(dict): table values
        Returns:
            str: storcli table populated with data
        """

        value_rows = []

        # store row with the max char count in a column
        header_lengths = {key: len(str(key)) for key in headers}

        for table_row in table_options:

            row_str = ""
            for col_key in headers:
                val_len = len(str(table_row[col_key]))
                # whitespace padding
                val_len = val_len if val_len >= len(col_key) else len(col_key)

                if val_len > header_lengths[col_key]:
                    header_lengths[col_key] = val_len

                row_str += '{val:<{width}}'.format(val=table_row[col_key], width=val_len+1)

            value_rows.append(row_str)

        header = ' '.join(['{val:<{width}}'.format(val=key, width=header_lengths[key]) for key in header_lengths])
        divider = '-'*len(header) + '\n'

        return str(
            divider + 
            header + '\n' + 
            divider + 
            '\n'.join(value_rows) + '\n' + 
            divider 
        )


    def _get_state_from_config(self, config_entry, current_state, optimal):
        """Configure state based on the configuration json file"""
        s_conf = self._storcli_details['stateConfig'][config_entry]
        for status in s_conf:
            for prop in current_state:
                if current_state[prop] >= s_conf[status][prop] and s_conf[status][prop] != -1 and status != optimal:
                    return status

        return optimal



    def _get_virtual_drives(self, controller_num):
        """Retrieve virtual drive data"""

        drives = []

        with self._graph_ref.get_session() as session:

            vd_details = GraphReference.get_virtual_drive_details(session, self._server_key, controller_num)
            cv_info = GraphReference.get_cachevault(session, self._server_key, controller_num)

            # iterate over virtual drives
            for i, v_drive in enumerate(vd_details):
                vd_state = copy.deepcopy(self._storcli_details['stateConfig']['virtualDrive']['Optl'])

                # Add Virtual Drive output
                v_drive['DG/VD'] = '0/' + str(i)
                v_drive['Size'] = str(v_drive['Size']) + ' GB'

                if cv_info['replacement'] == 'Yes' and cv_info['writeThrough']:
                    v_drive['Cache'] = 'RWTD'

                # Add physical drive output (do some formatting plus check pd states)
                for p_drive in v_drive['pd']:
                    p_drive['EID:Slt'] = '{}:{}'.format(p_drive['EID'], p_drive['slotNum'])
                    p_drive['Size'] = str(p_drive['Size']) + ' GB'

                    vd_state['mediaErrorCount'] += p_drive['mediaErrorCount']
                    vd_state['otherErrorCount'] += p_drive['otherErrorCount']

                    if p_drive['State'] == 'Offln':
                        vd_state['numPdOffline'] += 1
                
                v_drive['State'] = self._get_state_from_config('virtualDrive', vd_state, 'Optl')

                drives.append({
                    'physical_drives': self._format_as_table(StorCLIEmulator.pd_header, v_drive['pd']),
                    'virtual_drives': self._format_as_table(StorCLIEmulator.vd_header, [v_drive]),
                    'virtual_drives_num': i
                })

            return drives

    def _strcli_ctrl_virt_disk(self, controller_num):
        """Display virtual disk details """

        vd_file = os.path.join(self._storcli_dir, 'virtual_drive_data')
        with open(vd_file) as templ_h:

            template = Template(templ_h.read())

            # get virtual & physical drive details
            drives = self._get_virtual_drives(controller_num)
            vd_output = map(lambda d: template.substitute({**d, **{'controller': controller_num}}), drives)

            return self._strcli_header(controller_num) + '\n' + '\n'.join(vd_output)
        

    def _listen_cmds(self, socket_port):
        """Start storcli websocket server """

        serversocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        serversocket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        serversocket.bind(('', socket_port))
        serversocket.listen(5)

        conn, _ = serversocket.accept()

        with conn:
            while True:

                data = conn.recv(1024)
                if not data:
                    break
                
                try:
                    received = json.loads(data)
                except json.decoder.JSONDecodeError as parse_err:
                    logging.info(data)
                    logging.info('Invalid JSON: ')
                    logging.info(parse_err)

                argv = received['argv']

                logging.info('Data received: %s', str(received))

                reply = {"stdout": "", "stderr": "", "status": 0}

                # Process non-default return cases
                if len(argv) == 2:
                    if argv[1] == "--version":
                        reply['stdout'] = "Version 0.01"

                elif len(argv) == 3:
                    if argv[1] == "show" and argv[2] == "ctrlcount":
                        reply['stdout'] = self._strcli_ctrlcount()

                # Controller Commands
                elif len(argv) == 4 and argv[1].startswith("/c"):
                    if argv[2] == "show" and argv[3] == "perfmode":
                        reply['stdout'] = self._strcli_ctrl_perf_mode(argv[1][-1])
                    elif argv[2] == "show" and argv[3] == "bgirate":
                        reply['stdout'] = self._get_rate_prop(argv[1][-1], 'bgi_rate')
                    elif argv[2] == "show" and argv[3] == "ccrate":
                        reply['stdout'] = self._get_rate_prop(argv[1][-1], 'cc_rate')
                    elif argv[2] == "show" and argv[3] == "rebuildrate":
                        reply['stdout'] = self._get_rate_prop(argv[1][-1], 'rebuild_rate')
                    elif argv[2] == "show" and argv[3] == "prrate":
                        reply['stdout'] = self._get_rate_prop(argv[1][-1], 'pr_rate')
                    elif argv[2] == "show" and argv[3] == "alarm":
                        reply['stdout'] = self._strcli_ctrl_alarm_state(argv[1][-1])
                    elif argv[2] == "show" and argv[3] == "all":
                        reply['stdout'] = self._strcli_ctrl_info(argv[1][-1])

                elif len(argv) == 5 and argv[1].startswith("/c"):
                    if argv[2] == "/bbu" and argv[3] == "show" and argv[4] == "all":
                        reply['stdout'] = self._strcli_ctrl_bbu(argv[1][-1])
                    elif argv[2] == "/cv" and argv[3] == "show" and argv[4] == "all":
                        reply['stdout'] = self._strcli_ctrl_cachevault(argv[1][-1])
                    elif argv[2] == "/vall" and argv[3] == "show" and argv[4] == "all":
                        reply['stdout'] = self._strcli_ctrl_virt_disk(argv[1][-1])
                elif len(argv) == 6 and argv[1].startswith("/c"):
                    if argv[2] == "/eall" and argv[3] == "/sall" and argv[4] == "show" and argv[5] == "all":
                        reply['stdout'] = self._strcli_ctrl_phys_disks(argv[1][-1])
                else:
                    reply = {"stdout": "", "stderr": "Usage: " + argv[0] +" --version", "status": 1}

                # Send the message
                conn.sendall(bytes(json.dumps(reply) +"\n", "UTF-8"))
