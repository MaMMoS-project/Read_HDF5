# -*- coding: utf-8 -*-
"""
This code snippet is a collection of functions used to read and process
EDX (Energy-Dispersive X-ray spectroscopy) data from XML files (.spx)
and write it to HDF5 files.

@author: williamrigaut
"""

import xml.etree.ElementTree as et
import pathlib
import h5py
import numpy as np
from packages.compilers.compile_hdf5 import get_all_keys, convertFloat


def visit_items(item, edx_dict={}):
    """
    Recursively visits XML elements to build a nested dictionary representation.

    This function processes an XML element and its children, forming a hierarchy
    of dictionaries where each key represents an XML tag or type. Elements with
    specific tags listed in `parse_ignore` are skipped. If an element has no
    children, its text is added as a value in the dictionary. Otherwise, the
    function is called recursively to process its children.

    Args:
        item (xml.etree.ElementTree.Element): The XML element to process.
        edx_dict (dict, optional): The dictionary to update with parsed data.
            Defaults to an empty dictionary.

    Returns:
        dict: A nested dictionary representing the structure of the XML elements.
    """
    parse_ignore = [
        "",
        "DetLayers",
        "ShiftData",
        "PPRTData",
        "ResponseFunction",
        "Channels",
        "WindowLayers",
    ]

    if item.tag == "ClassInstance" and item.attrib["Type"] == "TRTPSEElement":
        parent_name = item.attrib["Type"] + " " + item.attrib["Name"]
    elif item.tag == "Result" or item.tag == "ExtResults":
        for child in item.iter():
            if child.tag == "Atom":
                parent_name = item.tag + " " + child.text
    elif item.tag == "ClassInstance":
        parent_name = item.attrib["Type"]
    else:
        parent_name = item.tag

    edx_dict.update({parent_name: {}})
    for child in item:
        if child.tag in parse_ignore:
            continue
        elif child.findall("./") == []:
            edx_dict[parent_name][child.tag] = child.text
        else:
            edx_dict = visit_items(child, edx_dict)

    return edx_dict


def get_channels(xml_root):
    """
    Extracts the channel data from an XML root element to a list of counts.

    Args:
        xml_root (xml.etree.ElementTree.Element): The root element of the XML tree.

    Returns:
        list: A list of strings representing the channel data extracted from the XML.
    """
    channels = []

    for elm in xml_root.iter("Channels"):
        channels = [int(counts) for counts in elm.text.split(",")]

    return channels


def read_data_from_spx(filepath):
    """
    Reads data from an XML file (.spx) containing EDX data exported from BRUKER instrument.

    Args:
        filepath (str or Path): The path to the XML file to read.

    Returns:
        tuple: A tuple containing a dictionary of metadata and a list of channel counts.
    """
    # Parse the XML file
    root = et.parse(filepath).getroot()[1]

    # Extract the data and metadata from xml
    edx_dict = visit_items(root)
    channels = get_channels(root)

    return edx_dict, channels


def get_scan_numbers(filepath):
    """
    Extracts the scan numbers (x and y indices) from the filename of the given
    filepath.

    Args:
        filepath (str or Path): The path to the EDX data file (.spx)

    Returns:
        tuple: A tuple containing the x and y indices of the scan
    """
    if isinstance(filepath, str):
        filename = filepath.split("/")[-1]
    elif isinstance(filepath, pathlib.Path):
        filename = filepath.name
    else:
        raise TypeError("filepath must be a string or pathlib.Path")

    x_idx, y_idx = filename.split(".spx")[0].split("(")[-1].split(")")[0].split(",")

    return int(x_idx), int(y_idx)


def get_wafer_positions(scan_numbers, step_x=5, step_y=5, start_x=-40, start_y=-40):
    """
    Calculates the wafer positions based on scan numbers and specified step and start values.

    Args:
        scan_numbers (tuple): A tuple containing the x and y indices of the scan.
        step_x (int, optional): The step size in the x direction. Defaults to 5.
        step_y (int, optional): The step size in the y direction. Defaults to 5.
        start_x (int, optional): The starting position in the x direction. Defaults to -40.
        start_y (int, optional): The starting position in the y direction. Defaults to -40.

    Returns:
        tuple: A tuple containing the calculated x and y positions on the wafer.
    """
    x_idx, y_idx = scan_numbers
    x_pos, y_pos = (x_idx - 1) * step_x + start_x, (y_idx - 1) * step_y + start_y

    return x_pos, y_pos


def get_units(key):
    dict_units = {
        "PrimaryEnergy": "keV",
        "WorkingDistance": "mm",
        "CalibAbs": "keV",
        "CalibLin": "keV",
        "DetectorTemperature": "°C",
        "DetectorThickness": "mm",
        "SiDeadLayerThickness": "mm",
        "AtomPercent": "at.%",
        "MassPercent": "mass.%",
    }

    if key in dict_units.keys():
        return dict_units[key]
    return None


def set_instrument_and_result_from_dict(edx_dict, instrument_group, result_group):
    """
    Writes the contents of the edx_dict dictionary to the HDF5 instrument_group and result_group.

    Args:
        edx_dict (dict): A dictionary containing the EDX data and metadata, generated by the visit_items function.
        instrument_group (h5py.Group): The HDF5 group to write the instrument data to.
        result_group (h5py.Group): The HDF5 group to write the result data to.
    Returns:
        None
    """
    for key, value in get_all_keys(edx_dict):
        if isinstance(value, dict):
            if [key for key in value.keys()] == []:
                continue
            elif key.startswith("Result") or key == "TRTResult":
                instrument_subgroup = result_group.create_group(key)
            elif key.startswith("ExtResults"):
                instrument_subgroup = result_group[f"Result {value["Atom"]}"]
                del instrument_subgroup["Atom"]
            elif key.startswith("TRTPSEElement"):
                tmp_group = result_group[f"Result {value["Element"]}"]
                new_key = f"Element {key.replace('TRTPSEElement ', '')}"
                result_group[new_key] = tmp_group
                instrument_subgroup = result_group[new_key]

                del result_group[f"Result {value["Element"]}"]
                del instrument_subgroup["Atom"]
            else:
                instrument_subgroup = instrument_group.create_group(
                    f"{key}".replace("TRT", "")
                )

            for subkey, subvalue in get_all_keys(value):
                if subvalue is not None:
                    if subkey == "AtomPercent" or subkey == "MassPercent":
                        # Convert values to .%
                        instrument_subgroup[subkey] = convertFloat(subvalue) * 100
                    else:
                        instrument_subgroup[subkey] = convertFloat(subvalue)
                    if get_units(subkey) is not None:
                        instrument_subgroup[subkey].attrs["units"] = get_units(subkey)


def make_energy_dataset(edx_dict, channels):
    """
    Calculates the energy array for the EDX data based on the values in
    the edx_dict dictionary.

    Args:
        edx_dict (dict): A dictionary containing the EDX data and metadata, generated by the visit_items function.
        channels (list): A list of channel counts, generated by the read_data_from_spx function.

    Returns:
        numpy.ndarray: An array of energy values corresponding to the channels.

    Notes:
        The energy calculation is based on the values in the edx_dict dictionary,
        specifically the "CalibAbs" and "CalibLin" values.
    """
    zero_energy = convertFloat(edx_dict["TRTSpectrumHeader"]["CalibAbs"])
    energy_step = convertFloat(edx_dict["TRTSpectrumHeader"]["CalibLin"])

    energy = np.array(
        [((i + 1) * energy_step + zero_energy) for i in range(len(channels) // 2)]
    )

    return energy


def write_edx_to_hdf5(HDF5_path, filepath, mode="a"):
    """
    Writes the contents of the EDX data file (.spx) to the given HDF5 file.

    Args:
        HDF5_path (str or Path): The path to the HDF5 file to write the data to.
        filepath (str or Path): The path to the EDX data file (.spx).
        mode (str, optional): The mode to open the HDF5 file in. Defaults to "a".

    Returns:
        None
    """
    scan_numbers = get_scan_numbers(filepath)
    wafer_positions = get_wafer_positions(scan_numbers)
    edx_dict, channels = read_data_from_spx(filepath)
    energy = make_energy_dataset(edx_dict, channels)

    with h5py.File(HDF5_path, mode) as f:
        scan_group = f"/entry/edx/scan_{scan_numbers[0]},{scan_numbers[1]}/"
        scan = f.create_group(scan_group)

        instrument = scan.create_group("instrument")
        instrument.attrs["NX_class"] = "HTinstrument"

        # Saving wafer positions with the units
        instrument["x_pos"] = wafer_positions[0]
        instrument["y_pos"] = wafer_positions[1]
        instrument["x_pos"].attrs["units"] = "mm"
        instrument["y_pos"].attrs["units"] = "mm"

        results = scan.create_group("results")
        results.attrs["NX_class"] = "HTresult"
        set_instrument_and_result_from_dict(edx_dict, instrument, results)

        data = scan.create_group("measurement")
        data.attrs["NX_class"] = "HTdata"

        counts = data.create_dataset(
            "counts", (len(channels),), data=channels, dtype="int"
        )
        energy = data.create_dataset(
            "energy", (len(energy),), data=energy, dtype="float"
        )
        counts.attrs["units"] = "cps"
        energy.attrs["units"] = "keV"

    return None
