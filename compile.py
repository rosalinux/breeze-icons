#!/usr/bin/python3

"""
SPDX-License-Identifier: LGPL-2.1-only OR LGPL-3.0-only OR LicenseRef-KDE-Accepted-LGPL
SPDX-FileCopyrightText: 2021 Ken Vermette <vermette@gmail.com>
"""

import os
import sys
import re
import time
import utilities as utils
import soup_svg_tools as soupsvg
import soup_xml_tools as soupxml

import pprint

import configparser
from lxml import etree
from bs4 import BeautifulSoup

"""
Builds icons from src assets using specifications from cookbook.ini files
"""

# Paths
BUILD_PATH     = os.getcwd() + "/build"
SRC_PATH       = os.getcwd() + "/src"
COOKBOOKS_PATH = os.getcwd() + "/src"
CONFIG_PATH    = os.getcwd() + "/src"

pp = pprint.PrettyPrinter(indent=4)

def main():
    main_start_time = time.perf_counter()
    main_error_count = 0
    main_built_count = 0
    
    print("Building all cookbooks")
    
    for f in os.listdir(COOKBOOKS_PATH):
        if not f.endswith(".cookbook.ini"):
            continue
        
        book_start_time = time.perf_counter()
        book_error_count = 0
        book_built_count = 0
        print("Building ", f)
        
        cookbook = unpack_cookbook(os.path.join(COOKBOOKS_PATH, f))
        
        for icon in cookbook["recipes"]:
            recipe = cookbook["recipes"][icon]
            
            for size in recipe["sizes"]:
                try:
                    icon_start_time = time.perf_counter()
                    folder = os.path.join(BUILD_PATH, recipe["folder"], size)
                    path = os.path.join(folder, icon + ".svg")
                    soup = build_recipe(recipe, cookbook, size)
                    
                    if soup == False:
                        continue
                    
                    optimize_svg(soup, cookbook)
                    write_minified_svg(soup, path)
                    make_relative_symlinks(path, recipe["aliases"])

                    book_built_count += 1
                    main_built_count += 1
                    icon_end_time = time.perf_counter()
                    utils.log_icon_state("done", {
                        "icon":    icon,
                        "size":    size,
                        "context": recipe["context"],
                        "message": "Built in " + str(round(icon_end_time-icon_start_time, 3)) + "s"
                        })
                
                except Exception as error:
                    book_error_count += 1
                    main_error_count += 1
                    utils.log_icon_state("fail", {
                        "icon":    icon,
                        "size":    size,
                        "context": recipe["context"],
                        "message": error,
                        })
        book_end_time = time.perf_counter()
        print("Built", book_built_count, "icons for ", f, "in", str(round(book_end_time-book_start_time, 3)) + "s with", book_error_count, "error(s)")
        
    main_end_time = time.perf_counter()
    print("Compilation created", main_built_count, "icons total in", str(round(main_end_time-main_start_time, 3)) + "s with", main_error_count, "error(s)")


## Parse a cookbooks configuration settings
def unpack_cookbook(path):
    config = configparser.ConfigParser(strict=False,delimiters=["="])
    config.optionxform=str
    config.read(path)
    
    defaults = config._sections["Defaults"] if "Defaults" in config._sections else {}
    palette  = config._sections["Palette"]  if "Palette"  in config._sections else {}
    general  = config._sections["Cookbook"] if "Cookbook" in config._sections else {}
    cookbook = {
        "palette": palette,
        "abspath": os.path.dirname(path),
        "recipes": {},
        "reserved_ids": general["reserved-ids"] if "reserved-ids" in general else [],
        "remove_css_suffixes": utils.csv_to_list(general["remove-css-suffixes"]) if "remove-css-suffixes" in general else [],
        "remove_elements": utils.key_to_dict("remove", general)
        }
    
    if "Cookbook" in config:
        del config["Cookbook"]
        
    if "Defaults" in config:
        del config["Defaults"]
        
    if "Palette" in config:
        del config["Palette"]
        
    default_settings = {
        "sizes":   utils.csv_to_list(defaults["sizes"]) if "sizes" in defaults else [],
        "context": defaults["context"] if "context" in defaults else "Generic",
        "folder":  defaults["folder"]  if "folder"  in defaults else "generic",
        "base":    defaults["base"]    if "base"    in defaults else "undefined",
        }
    
    for icon_name in config.sections():
        icon = config[icon_name]
        cookbook["recipes"][icon_name] = {
            "name":         icon_name,
            
            "sizes":   utils.priority_dict_value("sizes",   icon, default_settings, []),
            "context": utils.priority_dict_value("context", icon, default_settings, "Generic"),
            "folder":  utils.priority_dict_value("folder",  icon, default_settings, "generic"),
            "base":    utils.priority_dict_value("base",    icon, default_settings, "undefined"),
            
            "template": icon["template"] if "template" in icon else "undefined",
            "aliases":  utils.csv_to_list(icon["aliases"]) if "aliases" in icon else [],
            "classes":  utils.key_to_dict("classes", icon),
            "attrs":    utils.key_to_dict("attr",    icon),
            "replace":  utils.key_to_dict("replace", icon),
            }
        
    return cookbook


## Build one icon of a given size
def build_recipe(recipe, cookbook, size):
    path_base =     os.path.join(cookbook["abspath"], recipe["base"] + "." + size + ".svg")
    path_template = os.path.join(cookbook["abspath"], recipe["template"])
    
    soup = BeautifulSoup(utils.get_file_contents(path_base), "xml")
    soup = soupsvg.replace_selector_with_svg_file(soup, "#content", path_template)
    
    for target in recipe["replace"]:
        svg_path = os.path.join(cookbook["abspath"], recipe["replace"][target])
        soupsvg.replace_selector_with_svg_file(soup, target, svg_path)
    
    for selector in recipe["classes"]:
        soupsvg.modify_selector_classes(soup, selector, recipe["classes"][selector])
    
    soupsvg.r_style_to_attrs(soup) # Move styles to attrs before modifying attrs.

    for selector in recipe["attrs"]:
        for tag in soup.select(selector):
            for attr_key in recipe["attrs"][selector]:
                attr_value = recipe["attrs"][selector][attr_key]
                tag[attr_key] = string_alias(attr_value, cookbook["palette"])
    
    for tag in soup.select("[class]"):
        for suffix in cookbook["remove_css_suffixes"]:
            tag["class"] = re.sub(re.escape(suffix) + "[\s\n\t\r]|" + re.escape(suffix) + "$", " ", tag["class"])
    
    for removal in cookbook["remove_elements"]:
        for tag in soup.select(removal):
            tag.decompose()
    
    return soup.svg


## Runs the optimization functions on a soup object
def optimize_svg(soup, cookbook):
    soupxml.remove_comments(soup) # should be first to void errors.
    #soupsvg.r_style_to_attrs(soup) # should be second to enable the most functionality
    soupsvg.r_remove_default_attrs(soup)
    soupsvg.r_remove_redundant_attrs(soup)
    soupsvg.r_remove_inkscape_ids(soup, cookbook["reserved_ids"])
    soupsvg.remove_inkscape_attrs(soup)
    soupsvg.remove_unused_definitions(soup)
    soupsvg.recycle_identical_defs(soup)
    soupsvg.recycle_identical_paths(soup) # should be next-to-last
    soupsvg.optimise_attr_precision(soup)
    soupsvg.optimise_ids(soup, cookbook["reserved_ids"]) # should be after any operation involving ID manipulation.


## Parse a cookbooks configuration settings
def write_minified_svg(soup, path):
    file_contents = soupsvg.strip_namespaces(soup)
    
    if not os.path.exists(os.path.dirname(path)):
        os.makedirs(os.path.dirname(path))
    
    with open(path, "w") as file_handle:
        file_handle.write(file_contents)


## Makes a series of symlinks, paths relative to the origin file
def make_relative_symlinks (target, aliases):
    target_dir =  os.path.dirname(target)
    target_name = os.path.basename(target)
    
    for alias in aliases:
        alias_path = os.path.join(target_dir, alias + ".svg")
        
        if os.path.isfile(alias_path):
            if os.path.islink(alias_path) and os.readlink(alias_path) != target_name:
                os.remove(alias_path)
            elif os.path.islink(alias_path):
                continue
        
        if not os.path.isfile(alias_path):
            os.symlink(target_name, alias_path)


##
def string_alias (string, palette):
	string = string.strip("\"' \t\n\r")
	if string.startswith("@") and string[1:] in palette:
		return palette[string[1:]].strip("\"' \t\n\r")
	return string


##
## Zhu Li, do the thing!
##
if __name__ == '__main__':
    main()



"""



## Run one individual cookbook
def run_cookbook(path):
	global g_colors
	print("\nOpening Cookbook \"" + f + "\"\n")
	parser = configparser.ConfigParser(strict=False,delimiters=["="])
	parser.optionxform=str
	parser.read(path)
	
	settings = parser._sections["Cookbook"];
	sizes    = settings["sizes"].split(",") if "sizes" in settings else []
	context  = settings["context"] if "context" in settings else "Generic"
	folder   = settings["folder"] if "folder" in settings else "generic"
	g_colors = parser._sections["CookbookColors"] if "CookbookColors" in parser._sections else {}
	global_recipe = parser._sections["GlobalRecipes"] if "GlobalRecipes" in parser._sections else {}
	global_mixins = {
		"classes": extract_subvalue("classes", global_recipe),
		"replacements": extract_subvalue("replace", global_recipe),
	}
	
	if "Cookbook" in parser:
		del parser["Cookbook"]
		
	if "GlobalRecipes" in parser:
		del parser["GlobalRecipes"]
		
	if "CookbookColors" in parser:
		del parser["CookbookColors"]
	
	for section in parser.sections():
		icon = parser[section]
		
		for size in sizes:
			recipe = {
				"name": section,
				"context": folder,
				"size": size,
				"template": icon["template"] if "template" in icon else "undefined",
				"aliases": icon["aliases"].split(",") if "aliases" in icon else [],
				"classes": extract_subvalue("classes", icon),
				"attrs": utils.key_to_dict("attr", icon),
				"replacements": extract_subvalue("replace", icon),
			}
			
			build_result = build_recipe(recipe, global_mixins)
			
			# If the build failed stop here so we don't write garbage files
			if build_result == False:
				continue
			
			file_contents = build_result.prettify()
			file_dir = os.path.join(export_path, folder, size)
			file_dest = os.path.join(file_dir, section + ".svg")
			
			file_contents = '<?xml version="1.0" encoding="UTF-8" standalone="no" ?>' + "\n" + file_contents
			
			for ns in namespaces:
				file_contents = file_contents.replace("<" + ns + ":", "<").replace("</" + ns + ":", "</")
			
			if not os.path.exists(file_dir):
				os.makedirs(file_dir)
				
			with open(file_dest, "w") as file_handle:
				file_handle.write(file_contents)
			
			#recipe["aliases"].append(section + ".gen")
			
			for alias in recipe["aliases"]:
				alias_name = alias.strip()
				alias_path = os.path.join(file_dir, alias_name + ".svg")
				alias_target = section + ".svg"
				
				if alias_name == "":
					continue
				if os.path.isfile(alias_path):
					if os.path.islink(alias_path) and os.readlink(alias_path) != alias_target:
						os.remove(alias_path)
					elif os.path.islink(alias_path):
						#log_icon_state("done", recipe, "Alias " + alias_name)
						continue
					else:
						#log_icon_state("skip", recipe, "Alias not created: " + alias_name + " is a real file")
						continue
				
				#log_icon_state("done", recipe, "Alias " + alias_name)
				os.symlink(alias_target, alias_path)



def build_recipe (recipe, mixins):
	mas_path = os.path.join(masters_path, "master." + recipe["size"] + ".svg")
	tpl_path = os.path.join(template_path, recipe["template"] + "." + recipe["size"] + ".svg")
	
	if not os.path.isfile(mas_path):
		log_icon_state("fail", recipe, "Missing master: " + mas_path)
		return False
	
	if not os.path.isfile(tpl_path):
		log_icon_state("fail", recipe, "Missing base template: " + tpl_path)
		return False
	
	master_src = utils.get_file_contents(mas_path)
	template_src = utils.get_file_contents(tpl_path)
	
	soup = BeautifulSoup(master_src, tag_parser)
	template_soup = BeautifulSoup(template_src, tag_parser)
	
	for contents in soup.select("#content"):
		xml.merge_singleton_tag("defs", template_soup, soup, tpl_path)
		contents.replace_with(xml.select_to_g("svg > *:not(defs)", template_soup, "content"))
	
	for target in recipe["replacements"]:
		soup = xml.do_positioned_replacement(target, recipe["replacements"][target], soup, recipe)
		if not soup:
			return False
	
	for selector in recipe["classes"]:
		soup = xml.select_class_mod(selector, recipe["classes"][selector], soup)
	
	
	for selector in recipe["attrs"]:
		for tag in soup.select(selector):
			for attr_key in recipe["attrs"][selector]:
				attr_value = recipe["attrs"][selector][attr_key]
				tag[attr_key] = string_alias(attr_value)
	
	
	xml.clean_classes(soup)
	log_icon_state("done", recipe)
	return soup.svg


"""


"""

## Misc
tag_parser = "xml"
build_log  = []
singletons_loaded = []
namespaces = ["svg", "xml", "sodipodi", "inkscape"]
g_colors = {"foo":"bar"}


## Run one individual cookbook
def run_cookbook(path):
	global g_colors
	print("\nOpening Cookbook \"" + f + "\"\n")
	parser = configparser.ConfigParser(strict=False,delimiters=["="])
	parser.optionxform=str
	parser.read(path)
	
	settings = parser._sections["Cookbook"];
	sizes    = settings["sizes"].split(",") if "sizes" in settings else []
	context  = settings["context"] if "context" in settings else "Generic"
	folder   = settings["folder"] if "folder" in settings else "generic"
	g_colors = parser._sections["CookbookColors"] if "CookbookColors" in parser._sections else {}
	global_recipe = parser._sections["GlobalRecipes"] if "GlobalRecipes" in parser._sections else {}
	global_mixins = {
		"classes": extract_subvalue("classes", global_recipe),
		"replacements": extract_subvalue("replace", global_recipe),
	}
	
	if "Cookbook" in parser:
		del parser["Cookbook"]
		
	if "GlobalRecipes" in parser:
		del parser["GlobalRecipes"]
		
	if "CookbookColors" in parser:
		del parser["CookbookColors"]
	
	for section in parser.sections():
		icon = parser[section]
		
		for size in sizes:
			recipe = {
				"name": section,
				"context": folder,
				"size": size,
				"template": icon["template"] if "template" in icon else "undefined",
				"aliases": icon["aliases"].split(",") if "aliases" in icon else [],
				"classes": extract_subvalue("classes", icon),
				"attrs": utils.key_to_dict("attr", icon),
				"replacements": extract_subvalue("replace", icon),
			}
			
			build_result = build_recipe(recipe, global_mixins)
			
			# If the build failed stop here so we don't write garbage files
			if build_result == False:
				continue
			
			file_contents = build_result.prettify()
			file_dir = os.path.join(export_path, folder, size)
			file_dest = os.path.join(file_dir, section + ".svg")
			
			file_contents = '<?xml version="1.0" encoding="UTF-8" standalone="no" ?>' + "\n" + file_contents
			
			for ns in namespaces:
				file_contents = file_contents.replace("<" + ns + ":", "<").replace("</" + ns + ":", "</")
			
			if not os.path.exists(file_dir):
				os.makedirs(file_dir)
				
			with open(file_dest, "w") as file_handle:
				file_handle.write(file_contents)
			
			#recipe["aliases"].append(section + ".gen")
			
			for alias in recipe["aliases"]:
				alias_name = alias.strip()
				alias_path = os.path.join(file_dir, alias_name + ".svg")
				alias_target = section + ".svg"
				
				if alias_name == "":
					continue
				if os.path.isfile(alias_path):
					if os.path.islink(alias_path) and os.readlink(alias_path) != alias_target:
						os.remove(alias_path)
					elif os.path.islink(alias_path):
						#log_icon_state("done", recipe, "Alias " + alias_name)
						continue
					else:
						#log_icon_state("skip", recipe, "Alias not created: " + alias_name + " is a real file")
						continue
				
				#log_icon_state("done", recipe, "Alias " + alias_name)
				os.symlink(alias_target, alias_path)
	#print(build_log)


## Build an icon
def build_recipe (recipe, mixins):
	mas_path = os.path.join(masters_path, "master." + recipe["size"] + ".svg")
	tpl_path = os.path.join(template_path, recipe["template"] + "." + recipe["size"] + ".svg")
	
	if not os.path.isfile(mas_path):
		log_icon_state("fail", recipe, "Missing master: " + mas_path)
		return False
	
	if not os.path.isfile(tpl_path):
		log_icon_state("fail", recipe, "Missing base template: " + tpl_path)
		return False
	
	master_src = utils.get_file_contents(mas_path)
	template_src = utils.get_file_contents(tpl_path)
	
	soup = BeautifulSoup(master_src, tag_parser)
	template_soup = BeautifulSoup(template_src, tag_parser)
	
	for contents in soup.select("#content"):
		xml.merge_singleton_tag("defs", template_soup, soup, tpl_path)
		contents.replace_with(xml.select_to_g("svg > *:not(defs)", template_soup, "content"))
	
	for target in recipe["replacements"]:
		soup = xml.do_positioned_replacement(target, recipe["replacements"][target], soup, recipe)
		if not soup:
			return False
	
	for selector in recipe["classes"]:
		soup = xml.select_class_mod(selector, recipe["classes"][selector], soup)
	
	
	for selector in recipe["attrs"]:
		for tag in soup.select(selector):
			for attr_key in recipe["attrs"][selector]:
				attr_value = recipe["attrs"][selector][attr_key]
				tag[attr_key] = string_alias(attr_value)
	
	
	xml.clean_classes(soup)
	log_icon_state("done", recipe)
	return soup.svg


def string_alias (selector):
	global g_colors
	selector = selector.strip("\"' \t\n\r")
	if selector.startswith("@") and selector[1:] in g_colors:
		return g_colors[selector[1:]].strip("\"' \t\n\r")
	return selector


def log_icon_state (status, recipe, message = ""):
	build_log.append({
		"status": status,
		"context": recipe["context"],
		"name": recipe["name"],
		"size": recipe["size"],
		"message": message,
	})
	
	#print("[" + status + "]", recipe["context"].ljust(12), recipe["name"].ljust(24), recipe["size"].ljust(8), message)
	
	icon_label_len = 24
	
	if len(recipe["name"]) > icon_label_len:
		recipe["name"] = recipe["name"][0:icon_label_len - 3] + "..."
	
	print("[" + status + "]", recipe["name"].ljust(icon_label_len), recipe["size"].ljust(6), message)


##
def validate_str_list (string):
		if isinstance(string, str):
			return string.split()
		else:
			return string


##
def extract_subvalue (key, dictionary):
	output = {}
	for raw in dictionary:
		if raw.startswith(key + '["') and raw.endswith('"]'):
			newkey = raw.replace(key + '["',"").replace('"]',"")
			output[newkey] = dictionary[raw].strip("\"' \t\n\r")
	return output


## 
def position_to_offset (position):
	if position == "left" or position == "top":
		return -1
	elif position == "center":
		return 0
	elif position == "right" or position == "bottom":
		return -1
	return position


##
def log_icon (icon, sizes, state, text):
	pass


##
## Zhu Li, do the thing!
##
cookbooks = sys.argv
cookbooks.pop(0)

if len(cookbooks) == 0:
	print("Looking for all cookbooks in the /cookbooks folder")
	for f in os.listdir(cookbooks_path):
		if f.endswith(".cookbook"):
			run_cookbook(os.path.join(cookbooks_path, f))
else:
	for f in cookbooks:
		if os.path.isfile(os.path.join(os.getcwd(), f)):
			run_cookbook(os.path.join(os.getcwd(), f))
		else:
			print("File not found: \"" + f + '"')
			
"""