import json
import logging
import pathlib
import re
import time
from pprint import pprint
from typing import List, Optional, Tuple, Iterable, Dict, Union

logger = logging.getLogger(__name__)


class NameConflictError(BaseException):
    """Raise for errors in adding plugins due to the same name."""


class ParserNotFoundError(Exception):
    pass


class NoParserFilesFoundError(Exception):
    pass


class tabular_object:
    def __init__(self):
        self.entries: Dict = {}

    def __str__(self):
        return str(self.entries)


def oper_fill_tabular(right_justified: bool, header_fields: Union[List, Tuple], label_fields: Union[List, Tuple],
                      index: Union[List, Tuple], table_terminal_pattern:
                    str, device_output: str, device_os: str):
    table_entry = tabular_object()
    regex1 = r"\s*{}".format(header_fields[0].strip())
    for h in header_fields[1:]:
        regex1 = r"{}\s+{}".format(regex1, h.strip())
    # regex1 = r"{}\s*[\n\r]".format(regex1)
    print(regex1)
    c_regex1 = re.compile(regex1)
    headers_matched = False
    for line in device_output.splitlines():
        m1 = c_regex1.match(line)
        if m1 and not headers_matched:
            print(m1)
            # [\*\s]\s+\d+\s +\d +\s + [\w\-]+\s + [\w\.\-\(\)]+\s + [\w\-]+\s +\w +)
            regex2 = r"^(?P<{}>\*?\s*\S+)".format(label_fields[0].strip())
            for f in label_fields[1:]:
                regex2 = r"{}\s+(?P<{}>\S+)".format(regex2, f.strip())
            regex2 = "{}$".format(regex2)
            print(regex2)
            c_regex2 = re.compile(regex2)
            c_terminator = re.compile(table_terminal_pattern)
            headers_matched = True
            continue
        elif headers_matched:
            if right_justified:
                line = line.lstrip()
            m2 = c_regex2.match(line)
            if m2:
                print(line)
                print(m2.groupdict())
                table_entry.entries[m2.groupdict()['switch_num'].strip()] = {key: value.strip() for key, value in
                                                               m2.groupdict().items()}
                continue
            m2 = c_terminator.match(line)
            if m2:
                break

    print(table_entry)
    return table_entry


def _outer_command_check(cli_command_list, command):
    command_list = command.split()
    print(f"outer: {command_list}")
    for command_str in cli_command_list:
        cli_command_str_split = command_str.split()
        if '{' in command_str and len(cli_command_str_split) == len(command_list) and _inner_command_check(
                cli_command_str_split, command_list):
            return True
    return False


def _inner_command_check(cli_command_list, command_list) -> bool:
    for supp_command, cli_command in zip(command_list, cli_command_list):
        if '{' in cli_command:
            if supp_command.strip() == "{}".format(supp_command.strip()):
                continue
            else:
                return False
        elif supp_command.strip() == cli_command.strip():
            continue
        else:
            return False
    return True


class ParserEngine:
    # We are going to find and execute a parser for a command output
    def __init__(self, parser_dir: str = r"./src/genie/libs/parser"):
        self.parser_directory = parser_dir
        self.cache = {}

    def __call__(self, command: str, output: str, network_os: str = "nxos") -> str:
        """

        :param command: cli command, needs to match the command in the class cli_command = statement
        :type command: str
        :param output: command output to be parsed
        :type output: str
        :param network_os: network operating system, needs to match directory name in parser directory structure
        :type network_os: str
        :return: parsed output
        :rtype: json str
        """

        key_value = (command, network_os)
        if key_value in self.cache:
            print("Cache Hit")
            return json.dumps(self.cache[key_value].cli(output))
        path = pathlib.Path(self.parser_directory, network_os)
        files: List[pathlib.Path] = self._get_parser_modules(path)
        if not files:
            raise NoParserFilesFoundError("No files found at {}".format(path))
        print(files)
        cmd_module = self._find_command(command, files)
        if not cmd_module:
            raise ModuleNotFoundError("Parser Module for {} not found!".format(command))
        print(cmd_module)
        parser_name, parser_class = self._find_class(command, cmd_module)
        if not parser_name:
            raise ParserNotFoundError("Parser Class for {} not found in {}!".format(command, cmd_module))
        print(parser_name)
        #print(parser_class)
        parser_class = self._alter_class(parser_class)
        #print(parser_class)
        exec(parser_class, globals(), globals())
        exec("p = {}()".format(parser_name), globals(), globals())
        self.cache[key_value] = p

        result = p.cli(output=output)
        return json.dumps(result)

    def _get_parser_modules(self, path: pathlib.Path) -> List[pathlib.Path]:
        """Retrieve the list of parser modules for the supplied network os"""
        files = [f for f in path.iterdir() if
                 f.name.startswith('show_') or f.name.startswith('ping')]
        return files

    def _find_command(self, command: str, files: List[pathlib.Path], regex1: str=r"[\'\"](show.*?)[\'\"]") -> Optional[pathlib.Path]:
        "find the parser module containing the supplied command"
        c_regex1 = re.compile(regex1)
        for file in files:
            file_text = file.read_text()
            list_of_commands = c_regex1.findall(file_text)
            # print(list_of_commands)
            if command in list_of_commands:
                return file
            else:
                for cli_command in list_of_commands:
                    command_list = command.split()
                    cli_command_list = cli_command.split()
                    if '{' in cli_command and len(command_list) == len(cli_command_list):
                        for supp_command, cli_command in zip(command_list, cli_command_list):
                            if '{' in cli_command:
                                if supp_command.strip() == "{}".format(supp_command.strip()):
                                    continue
                                else:
                                    break
                            elif supp_command == cli_command:
                                continue
                            else:
                                break
                        else:
                            return file

    def _find_class(self, command: str, cmd_module: pathlib.Path, regex1: str=r"(class\s+?\w+)\((\w+?Schema)\):",
                    regex2: str=r"cli_command\s+?=\s+?['\"]{}['\"]") -> Optional[Tuple[str, str]]:
        "Find the parser class and return the name of the class and the string"
        regex2 = regex2.format(command)
        c_regex1 = re.compile(regex1)
        c_regex2 = re.compile(regex2)
        c_regex2_2 = re.compile(r"cli_command\s+?=\s+?(?P<cli_command_string>\[.*$)")
        c_regex2_3 = re.compile(r"(?P<cli_command_string>.*\])")
        present_class = None
        cli_command_flag = False
        cli_command_string = ""
        for line in cmd_module.read_text().splitlines():
            if cli_command_flag:
                #print("command flag")
                #print(line)
                match = c_regex2_3.search(line)
                if match:
                    cli_command_flag = False
                    cli_command_string = "{} {}".format(cli_command_string, match.groupdict()["cli_command_string"])
                    #print(f"match 2_3: {cli_command_string}")
                    cli_command_list = eval(cli_command_string)
                    print(f"cli_command: {cli_command_list}")
                    if command in cli_command_list:
                        break
                    elif _outer_command_check(cli_command_list, command):
                        break
                    cli_command_string = ""
                else:
                    cli_command_string = "{} {}".format(cli_command_string, line.strip())
                    #print(f"inter line: {cli_command_string}")
            match = c_regex1.search(line)
            if match:
                present_class = match
                continue
            match = c_regex2.search(line)
            if match:
                break
            match = c_regex2_2.search(line)
            if match:
                #print(f"match 2_2: {match.groupdict()}")
                cli_command_string = match.groupdict()["cli_command_string"]
                if "]" not in cli_command_string:
                    cli_command_flag = True
                else:
                    cli_command_list = eval(cli_command_string)
                    if command in cli_command_list:
                        break
                    elif _outer_command_check(cli_command_list, command):
                        break
        else:
            return None
        regex3 = r"({}\({}\):\s+.*?return\s+\S+[\n\r])[\n\r]+?(?:class|#)".format(present_class.group(1), present_class.group(2))
        c_regex3 = re.compile(regex3, re.S)
        match = c_regex3.search(cmd_module.read_text())
        print(match.groups())
        return present_class.group(1).split()[1], match.group(1)

    def _alter_class(self, parser_class: str, regex1: str=r"class\s+?\w+(\(\w+?Schema\)):"):
        "Alter the found parser class, so it can run, remove schema, remove call to device object"
        c_regex1 = re.compile(regex1)
        class_statement = c_regex1.search(parser_class)
        parser_class = parser_class.replace(class_statement.group(1), "")
        #print(parser_class)
        parser_class = parser_class.replace("""if output is None:
            out = self.device.execute(self.cli_command)
        else:
            out = output""", "out=output")
        parser_class = parser_class.replace("genie.parsergen.oper_fill_tabular", "oper_fill_tabular")
        #print(parser_class)
        return parser_class


if __name__ == '__main__':
    app = ParserEngine()

    show_ver = """Cisco Nexus Operating System (NX-OS) Software
    TAC support: http://www.cisco.com/tac
    Documents: http://www.cisco.com/en/US/products/ps9372/tsd_products_support_serie
    s_home.html
    Copyright (c) 2002-2020, Cisco Systems, Inc. All rights reserved.
    The copyrights to certain works contained herein are owned by
    other third parties and are used and distributed under license.
    Some parts of this software are covered under the GNU Public
    License. A copy of the license is available at
    http://www.gnu.org/licenses/gpl.html.

    Nexus 9000v is a demo version of the Nexus Operating System

    Software
      BIOS: version 
     NXOS: version 9.3(6)
      BIOS compile time:  
      NXOS image file is: bootflash:///nxos.9.3.6.bin
      NXOS compile time:  11/9/2020 23:00:00 [11/10/2020 11:00:21]


    Hardware
      cisco Nexus9000 C9300v Chassis 
      Intel(R) Xeon(R) CPU E5-2678 v3 @ 2.50GHz with 8161040 kB of memory.
      Processor Board ID 9AJ05VJPIV4

      Device name: leaf131
      bootflash:    4287040 kB
    Kernel uptime is 40 day(s), 20 hour(s), 55 minute(s), 10 second(s)

    Last reset 
      Reason: Unknown
      System version: 
      Service: 

    plugin
      Core Plugin, Ethernet Plugin

    Active Package(s):
    """
    start = time.time()
    pprint(app("show version", show_ver))
    end = time.time()
    print("Time for execution of program for {} order of computations: {}".format(
        app, round(end - start, 10)))

    start = time.time()
    pprint(app("show version", show_ver))
    end = time.time()
    print("Time for execution of program for {} : {}".format(
        app, end - start))

    show_ver = """Cisco IOS XE Software, Version 16.12.05
    Cisco IOS Software [Gibraltar], ASR1000 Software (X86_64_LINUX_IOSD-UNIVERSALK9-M), Version 16.12.5, RELEASE SOFTWARE (fc3)
    Technical Support: http://www.cisco.com/techsupport
    Copyright (c) 1986-2021 by Cisco Systems, Inc.
    Compiled Fri 29-Jan-21 12:08 by mcpre
    
    
    Cisco IOS-XE software, Copyright (c) 2005-2021 by cisco Systems, Inc.
    All rights reserved.  Certain components of Cisco IOS-XE software are
    licensed under the GNU General Public License ("GPL") Version 2.0.  The
    software code licensed under GPL Version 2.0 is free software that comes
    with ABSOLUTELY NO WARRANTY.  You can redistribute and/or modify such
    GPL code under the terms of GPL Version 2.0.  For more details, see the
    documentation or "License Notice" file accompanying the IOS-XE software,
    or the applicable URL provided on the flyer accompanying the IOS-XE
    software.
    
    
    ROM: 16.9(4r)
    
    al-oxdc-aar01 uptime is 1 year, 8 weeks, 21 hours, 39 minutes
    Uptime for this control processor is 1 year, 8 weeks, 21 hours, 42 minutes
    System returned to ROM by Image Install 
    System restarted at 03:37:14 gmt Sun Jun 20 2021
    System image file is "bootflash:packages.conf"
    Last reload reason: Image Install 
    
    
    
    This product contains cryptographic features and is subject to United
    States and local country laws governing import, export, transfer and
    use. Delivery of Cisco cryptographic products does not imply
    third-party authority to import, export, distribute or use encryption.
    Importers, exporters, distributors and users are responsible for
    compliance with U.S. and local country laws. By using this product you
    agree to comply with applicable laws and regulations. If you are unable
    to comply with U.S. and local laws, return this product immediately.
    
    A summary of U.S. laws governing Cisco cryptographic products may be found at:
    http://www.cisco.com/wwl/export/crypto/tool/stqrg.html
    
    If you require further assistance please contact us by sending email to
    export@cisco.com.
    
    License Type: Smart License is permanent
    License Level: adventerprise
    Next reload license Level: adventerprise
    
    The current crypto throughput level is 0 kbps 
    
    
    Smart Licensing Status: UNREGISTERED/EVAL EXPIRED
    
    cisco ASR1002-HX (2KH) processor (revision 2KH) with 3765187K/6147K bytes of memory.
    Processor board ID FXS2315Q3C4
    Crypto Hardware Module present
    8 Gigabit Ethernet interfaces
    8 Ten Gigabit Ethernet interfaces
    32768K bytes of non-volatile configuration memory.
    16777216K bytes of physical memory.
    29401087K bytes of eUSB flash at bootflash:.
    0K bytes of WebUI ODM Files at webui:.
    
    Configuration register is 0x2102
    """
    start = time.time()
    pprint(app("show version", show_ver, network_os="iosxe"))
    end = time.time()

    show_ver = """Cisco IOS XE Software, Version 16.12.05b
    Cisco IOS Software [Gibraltar], Catalyst L3 Switch Software (CAT3K_CAA-UNIVERSALK9-M), Version 16.12.5b, RELEASE SOFTWARE (fc3)
    Technical Support: http://www.cisco.com/techsupport
    Copyright (c) 1986-2021 by Cisco Systems, Inc.
    Compiled Thu 25-Mar-21 13:09 by mcpre
    
    
    Cisco IOS-XE software, Copyright (c) 2005-2021 by cisco Systems, Inc.
    All rights reserved.  Certain components of Cisco IOS-XE software are
    licensed under the GNU General Public License ("GPL") Version 2.0.  The
    software code licensed under GPL Version 2.0 is free software that comes
    with ABSOLUTELY NO WARRANTY.  You can redistribute and/or modify such
    GPL code under the terms of GPL Version 2.0.  For more details, see the
    documentation or "License Notice" file accompanying the IOS-XE software,
    or the applicable URL provided on the flyer accompanying the IOS-XE
    software.
    
    
    ROM: IOS-XE ROMMON
    BOOTLDR: CAT3K_CAA Boot Loader (CAT3K_CAA-HBOOT-M) Version 4.78, RELEASE SOFTWARE (P)
    
    ca-6mu1-ais02 uptime is 18 weeks, 6 days, 5 hours, 20 minutes
    Uptime for this control processor is 18 weeks, 6 days, 5 hours, 23 minutes
    System returned to ROM by Power Failure or Unknown at 06:30:20 gmt Mon Jul 15 2019
    System restarted at 19:58:15 gmt Tue Apr 5 2022
    System image file is "flash:packages.conf"
    Last reload reason: Power Failure or Unknown
    
    
    
    This product contains cryptographic features and is subject to United
    States and local country laws governing import, export, transfer and
    use. Delivery of Cisco cryptographic products does not imply
    third-party authority to import, export, distribute or use encryption.
    Importers, exporters, distributors and users are responsible for
    compliance with U.S. and local country laws. By using this product you
    agree to comply with applicable laws and regulations. If you are unable
    to comply with U.S. and local laws, return this product immediately.
    
    A summary of U.S. laws governing Cisco cryptographic products may be found at:
    http://www.cisco.com/wwl/export/crypto/tool/stqrg.html
    
    If you require further assistance please contact us by sending email to
    export@cisco.com.
    
    
    Technology Package License Information: 
    
    ------------------------------------------------------------------------------
    Technology-package                                     Technology-package
    Current                        Type                       Next reboot  
    ------------------------------------------------------------------------------
    ipbasek9            	Smart License                 	 ipbasek9            
    None                	Subscription Smart License    	 None                          
    
    
    Smart Licensing Status: UNREGISTERED/EVAL EXPIRED
    
    cisco WS-C3850-48P (MIPS) processor (revision AC0) with 794888K/6147K bytes of memory.
    Processor board ID FOC2222L024
    4 Virtual Ethernet interfaces
    104 Gigabit Ethernet interfaces
    8 Ten Gigabit Ethernet interfaces
    2048K bytes of non-volatile configuration memory.
    4194304K bytes of physical memory.
    252000K bytes of Crash Files at crashinfo:.
    252000K bytes of Crash Files at crashinfo-2:.
    1611414K bytes of Flash at flash:.
    1611414K bytes of Flash at flash-2:.
    0K bytes of WebUI ODM Files at webui:.
    
    Base Ethernet MAC Address          : 00:45:1d:25:5e:00
    Motherboard Assembly Number        : 73-15800-08
    Motherboard Serial Number          : FOC22205U0R
    Model Revision Number              : AC0
    Motherboard Revision Number        : B0
    Model Number                       : WS-C3850-48P
    System Serial Number               : FOC2222L024
    
    
    Switch Ports Model              SW Version        SW Image              Mode   
    ------ ----- -----              ----------        ----------            ----   
    *    1 56    WS-C3850-48P       16.12.05b         CAT3K_CAA-UNIVERSALK9 INSTALL
         2 56    WS-C3850-48P       16.12.05b         CAT3K_CAA-UNIVERSALK9 INSTALL
    
    
    Switch 02
    ---------
    Switch uptime                      : 18 weeks, 6 days, 5 hours, 23 minutes 
    
    Base Ethernet MAC Address          : 00:b6:70:30:b7:80
    Motherboard Assembly Number        : 73-15800-08
    Motherboard Serial Number          : FOC22205U5U
    Model Revision Number              : AC0
    Motherboard Revision Number        : B0
    Model Number                       : WS-C3850-48P
    System Serial Number               : FOC2222L054
    Last reload reason                 : Power Failure or Unknown
    
    Configuration register is 0x102"""

    start = time.time()
    pprint(app("show version", show_ver, network_os="iosxe"))
    end = time.time()

    show_o_neigh = """Neighbor ID     Pri   State           Dead Time   Address         Interface
10.100.128.205    0   FULL/  -        00:00:31    10.100.132.142  TenGigabitEthernet0/1/3
10.100.128.207    0   FULL/  -        00:00:38    10.100.132.150  TenGigabitEthernet0/1/1
10.100.128.206    0   FULL/  -        00:00:37    10.100.132.146  TenGigabitEthernet0/1/0"""
    start = time.time()
    pprint(app("show ip ospf neighbor", show_o_neigh, network_os="iosxe"))
    end = time.time()