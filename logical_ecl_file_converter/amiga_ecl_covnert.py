#! /usr/bin/env python3

import argparse
# import pwn
import struct
from PIL import Image

def planar_to_chunky(x, y, bitplanes):
    assert x % 8 == 0, 'strange x resolution'
    bytes_to_process = y * (x // 8)
    image_data = bytearray([0] * (x * y))
    for bitplane_index in range(len(bitplanes)):
        assert len(bitplanes[bitplane_index]) >= bytes_to_process, 'bitplane data too short'
        for one_pixel in range(len(image_data)):
            if (bitplanes[bitplane_index][one_pixel // 8] >> (7 - (one_pixel % 8) )) & 1 == 1:
                image_data[one_pixel] += 2 ** bitplane_index
    return image_data

def amiga_rgb_to_pc_rgb(amiga_rgb_values_in_words):
    palette = []
    for one_amiga_rgb_value in amiga_rgb_values_in_words:
        for rgb_element_to_parse in [8, 4, 0]:
            rgb_element = (one_amiga_rgb_value & (0x000f << rgb_element_to_parse)) >> rgb_element_to_parse
            rgb_element = rgb_element * 16 + rgb_element
            palette.append(rgb_element)
    return palette

def make_ehb_palette(palette):
    half_palette = []
    for rgb_element in palette:
        half_palette.append(rgb_element >> 1)
    return half_palette

def ecl_to_png():

    # load file

    with open(args.input, "rb") as file:
        file_content = bytearray(file.read())
    ecl_size = len(file_content)

    # extract pointers to compressed data from ecl file

    ecl_bitplane_pointers = []
    for one_pointer in range(ecl_pointer_count):
        value = struct.unpack('>L', file_content[one_pointer*ecl_bit_size:one_pointer*ecl_bit_size + ecl_bit_size])[0]
        ecl_bitplane_pointers.append(value)
    assert ecl_size == ecl_bitplane_pointers[-1], 'last pointer != file size'

    # extract palette from ecl file

    ecl_rgb_values = []
    for one_rgb_color in range(ecl_rgb_count):
        value = struct.unpack('>H', file_content[ecl_bit_size*7 + one_rgb_color*2:ecl_bit_size*7 + one_rgb_color*2 + 2])[0]
        ecl_rgb_values.append(value)

    # extract compressed bitplanes from ecl file

    ecl_bitplane_content = []
    for one_bitplane in range(ecl_pointer_count - 1):
        value = file_content[ecl_bitplane_pointers[one_bitplane]:ecl_bitplane_pointers[one_bitplane+1]]
        ecl_bitplane_content.append(value)

    # compressed data parser

    ecl_uncompressed_data = []
    for one_bitplane in range(len(ecl_bitplane_content)):
        stream_data = ecl_bitplane_content[one_bitplane]
        output_buffer = bytearray()
        stream_pointer = 0
        while stream_pointer < len(stream_data):
            stream_instruction = struct.unpack('>H',stream_data[stream_pointer:stream_pointer+2])[0]
            stream_instruction_length = stream_instruction & 0x3fff
            if (stream_instruction & 0xc000 == 0x0000):
                stream_pointer += 2
                output_buffer += b'\x00' * stream_instruction_length
            elif (stream_instruction & 0xc000 == 0xc000):
                stream_pointer += 2
                output_buffer += b'\xff' * stream_instruction_length
            elif (stream_instruction & 0xc000 != 0x0000):
                stream_pointer += 2
                output_buffer += stream_data[stream_pointer:stream_pointer+stream_instruction_length]
                stream_pointer += stream_instruction_length
            else:
                print("shouldn't be here..." )
                exit(1)
        ecl_uncompressed_data.append(output_buffer)

        # for stream comparison and debugging
        # print(len(output_buffer))
        # print(pwn.hexdump(output_buffer))

    palette = amiga_rgb_to_pc_rgb(ecl_rgb_values) + make_ehb_palette(amiga_rgb_to_pc_rgb(ecl_rgb_values))

    img = Image.frombytes('P', (image_x, image_y), planar_to_chunky(image_x, image_y, ecl_uncompressed_data))
    img.putpalette(palette)
    img.save(args.output)

def pc_rgb_to_amiga_rgb(palette):
    amiga_rgb_values_in_words = bytes()
    for one_rgb_color in range(image_color_count):
        amiga_color = 0x0000
        for rgb_index in range(3):
            amiga_color <<= 4
            amiga_color += palette[one_rgb_color * 3 + rgb_index] >> 4
        amiga_rgb_values_in_words += struct.pack('>H', amiga_color)
    return amiga_rgb_values_in_words

def chunky_to_planar(chunky_data):
    amiga_bitplanes = []
    for one_bitplane_index in range(ecl_bitplane_count):
        one_bitplane_data = bytes()
        for one_pack_of_8_pixels in range(len(chunky_data) // 8):
            one_pack_value = 0
            for one_bit in range(8):
                if (chunky_data[one_pack_of_8_pixels * 8 + (7 - one_bit)] >> one_bitplane_index ) & 1 == 1:
                    one_pack_value |= 1 << one_bit
            one_bitplane_data += struct.pack('B', one_pack_value)
        amiga_bitplanes.append(one_bitplane_data)
    return amiga_bitplanes

def compress_amiga_bitplane(one_bitplane):

    compressed_bitplane = bytes()

    # first 'image_skip_first_lines' should be ignored (for tilesets)

    compressed_bitplane += struct.pack('>H', image_skip_first_lines * (image_x // 8) | 0x0000)
    one_bitplane = one_bitplane[image_skip_first_lines * (image_x // 8):]

    # we have to compress 'one_bitplane' using repeated 0x00 or 0xff

    while len(one_bitplane) != 0:
        if one_bitplane[0:4] == b'\x00' * 4:
            for find_end in range(len(one_bitplane)):
                if one_bitplane[find_end] != 0:
                    break
                else:
                    find_end += 1
            compressed_bitplane += struct.pack('>H', find_end | 0x0000)
            one_bitplane = one_bitplane[find_end:]
        elif one_bitplane[0:4] == b'\xff' * 4:
            for find_end in range(len(one_bitplane)):
                if one_bitplane[find_end] != 0xff:
                    break
                else:
                    find_end += 1
            compressed_bitplane += struct.pack('>H', find_end | 0xc000)
            one_bitplane = one_bitplane[find_end:]
        else:
            for find_end in range(len(one_bitplane) - 4):
                if one_bitplane[find_end: find_end + 4] == b'\x00' * 4 or one_bitplane[find_end: find_end + 4] == b'\xff' * 4:
                    break
            else:
                find_end = len(one_bitplane)
            compressed_bitplane += struct.pack('>H', find_end | 0x4000)
            compressed_bitplane += one_bitplane[:find_end]
            one_bitplane = one_bitplane[find_end:]
    return compressed_bitplane

def png_to_ecl():

    # load image

    img = Image.open(args.input)
    assert img.width == image_x, 'wrong png size'
    assert img.height == image_y, 'wrong png size'
    assert img.mode == 'P', 'non indexed color image'
    assert len(img.palette.palette) == 3 * image_color_count * 2, 'invalid color number'

    # create amiga palette

    ecl_amiga_palette = pc_rgb_to_amiga_rgb(img.palette.palette[0:3 * image_color_count])

    # create amiga bitplanes

    amiga_bitplanes = chunky_to_planar(img.tobytes())

    # creatng ecl file

    ecl_file = bytearray([0] * (ecl_pointer_count * ecl_bit_size))
    ecl_file += ecl_amiga_palette

    for bitplane_index in range(len(amiga_bitplanes)):
        ecl_file[bitplane_index * ecl_bit_size:bitplane_index * ecl_bit_size + ecl_bit_size] = struct.pack('>L', len(ecl_file))
        ecl_file += compress_amiga_bitplane(amiga_bitplanes[bitplane_index])

    bitplane_index = ecl_bitplane_count
    ecl_file[bitplane_index * ecl_bit_size:bitplane_index * ecl_bit_size + ecl_bit_size] = struct.pack('>L', len(ecl_file))

    # save ecl file

    with open(args.output, "wb") as file:
        file.write(ecl_file)

# some constants

image_x = 320
image_y = 200
image_color_count = 32
image_ehb = True
image_skip_first_lines = 16

ecl_bit_size = 4
ecl_bitplane_count = 6
ecl_pointer_count = ecl_bitplane_count + 1
ecl_rgb_count = 32

# parse arguments

parser = argparse.ArgumentParser()
parser.add_argument('-m', '--mode', choices=['ecl2png', 'png2ecl'], required = True)
parser.add_argument('-i', '--input', required = True)
parser.add_argument('-o', '--output', required = True)
args = parser.parse_args()

# main program

if args.mode == 'ecl2png':
    ecl_to_png()
else:
    png_to_ecl()
