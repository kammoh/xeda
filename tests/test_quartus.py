from pathlib import Path
from xeda.flows.quartus import parse_csv


def test_parse_csv():
    parsed = parse_csv("tests/resources/Fitter_Resource_Utilization_by_Entity.csv", 'Compilation Hierarchy Node')
    assert parsed == {
        '|full_adder_piped': {
            'ALMs needed [=A-B+C]': '1.5 (1.5)',
            '[A] ALMs used in final placement': '1.5 (1.5)',
            '[B] Estimate of ALMs recoverable by dense packing': '0.0 (0.0)',
            '[C] Estimate of ALMs unavailable': '0.0 (0.0)',
            'ALMs used for memory': '0.0 (0.0)',
            'Block Memory Bits': '0',
            'Combinational ALUTs': '3 (3)',
            'Compilation Hierarchy Node': '|full_adder_piped',
            'DSP Blocks': '0',
            'Dedicated Logic Registers': '2 (2)',
            'Entity Name': 'full_adder_piped',
            'Full Hierarchy Name': '|full_adder_piped',
            'I/O Registers': '0 (0)',
            'Library Name': 'work',
            'M10Ks': '0',
            'Pins': '7',
            'Virtual Pins': '0',
        },
    }


def test_parse_csv_no_header():
    parsed = parse_csv("tests/resources/Flow_Summary.csv", None)
    assert parsed == {
        'Flow Status': 'Successful - Tue Mar  1 11:10:35 2022',
        'Quartus Prime Version': '21.1.0 Build 842 10/21/2021 SJ Lite Edition',
        'Revision Name': 'pipelined_adder',
        'Top-level Entity Name': 'full_adder_piped',
        'Family': 'Cyclone V',
        'Device': '5CGXBC3B6F23C7', 'Timing Models': 'Final',
        'Total registers': '2',
        'Total pins': '7 / 222 ( 3 % )',
        'Total virtual pins': '0',
        'Total DSP Blocks': '0 / 57 ( 0 % )',
        'Total HSSI RX PCSs': '0 / 3 ( 0 % )',
        'Total HSSI PMA RX Deserializers': '0 / 3 ( 0 % )',
        'Total HSSI TX PCSs': '0 / 3 ( 0 % )',
        'Total HSSI PMA TX Serializers': '0 / 3 ( 0 % )',
        'Total PLLs': '0 / 7 ( 0 % )', 'Total DLLs': '0 / 3 ( 0 % )'
    }
