import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
import os
import re

# --- Configuration ---
# XMLTV time format: YYYYMMDDHHMMSS +0800 (Assuming Asia/Manila time zone for all channels)
XMLTV_TIME_FORMAT = "%Y%m%d%H%M%S +0800"

# Map of uploaded text filenames to their unique XMLTV Channel IDs
CHANNEL_MAP = {
    'abante.txt': 'abante.ph',
    'aliw channel.txt': 'aliwchannel.ph',
    'congresstv.txt': 'congresstv.ph',
    'dzmm.txt': 'dzmm.ph',
    'dzrh.txt': 'dzrh.ph',
    'hbo boxing.txt': 'hboboxing.us',
    'iheartmovies.txt': 'iheartmovies.ph',
    'lighttv.txt': 'lighttv.ph',
    'untv.txt': 'untv.ph',
}

# Standard mapping of day names to datetime weekday indices (Monday is 0, Sunday is 6)
DAYS_OF_WEEK = {
    'MONDAY': 0, 'TUESDAY': 1, 'WEDNESDAY': 2, 'THURSDAY': 3,
    'FRIDAY': 4, 'SATURDAY': 5, 'SUNDAY': 6
}
# ---------------------

def parse_time_to_24h(time_str):
    """Converts 12-hour format time string (e.g., '5:30 AM') to 24-hour hour and minute."""
    if not time_str:
        return None, None
    
    # Normalize common variations
    time_str = time_str.replace('nn', ' PM').replace('am', ' AM').replace('pm', ' PM').strip().upper()

    try:
        # Use strptime to handle AM/PM conversion
        dt = datetime.strptime(time_str, '%I:%M %p')
        return dt.hour, dt.minute
    except ValueError:
        try:
            # Handle times without space (e.g., '12:00PM')
            dt = datetime.strptime(time_str, '%I:%M%p')
            return dt.hour, dt.minute
        except ValueError:
            print(f"Warning: Could not parse time string: '{time_str}'. Skipping program.")
            return None, None

def parse_schedule_file(filepath, channel_id):
    """Reads a text file, extracts day, time, and title, and returns sorted program segments."""
    programs = []
    current_day = None
    
    # Regex to capture time and title: TIME - TITLE (handles varying separators and whitespace)
    # The time group captures the 12-hour string (e.g., '10:30 AM', '12:00pm')
    program_line_re = re.compile(r'^\s*(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm|nn))\s*[-–]\s*(.*)\s*$', re.I) 
    
    # Specific regex for 'lighttv.txt' which uses multiple spaces instead of a dash
    lighttv_program_line_re = re.compile(r'^\s*(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))\s{2,}(.*)\s*$', re.I) 

    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            # Check for Day header (e.g., "Monday" or "MONDAY")
            upper_line = line.upper().replace('\r', '').replace('\n', '')
            if upper_line in DAYS_OF_WEEK:
                current_day = upper_line
                continue

            if not current_day:
                continue
            
            # --- Try to parse the program line based on filename heuristics ---
            match = None
            if 'lighttv.txt' in filepath.lower():
                 match = lighttv_program_line_re.match(line)
            else:
                 # Standard regex for most files
                 match = program_line_re.match(line)
                 
            if match:
                time_str, title = match.groups()
                time_str = time_str.strip()
                title = title.strip()
                if title:
                    programs.append({
                        'day': current_day,
                        'time_str': time_str,
                        'title': title,
                        'channel_id': channel_id
                    })

    # Pre-parse time for sorting and then sort by day index, hour, and minute
    parsed_programs = []
    for p in programs:
        hour, minute = parse_time_to_24h(p['time_str'])
        if hour is not None:
             p['hour'] = hour
             p['minute'] = minute
             p['day_index'] = DAYS_OF_WEEK[p['day']]
             parsed_programs.append(p)
             
    parsed_programs.sort(key=lambda x: (x['day_index'], x['hour'], x['minute']))
    
    # Remove temporary sorting keys before returning
    for p in parsed_programs:
        del p['hour']
        del p['minute']
        del p['day_index']
        
    return parsed_programs

def generate_xmltv(all_programs):
    """Generates the XMLTV structure from the parsed programs."""
    
    # Create the root element
    tv = ET.Element('tv', attrib={'source-info-url': 'https://github.com/epg-schedules', 
                                  'source-info-name': 'Custom EPG Schedules',
                                  'generator-info-name': 'EPG Parser Script'})

    # 1. Add <channel> entries
    channel_ids = sorted(list(set(p['channel_id'] for p in all_programs)))
    for chan_id in channel_ids:
        channel = ET.SubElement(tv, 'channel', attrib={'id': chan_id})
        display_name = ET.SubElement(channel, 'display-name', attrib={'lang': 'en'})
        # Use filename prefix as display name, capitalized
        display_name.text = chan_id.split('.')[0].upper()
        
    # 2. Add <programme> entries
    
    # Group programs by channel
    programs_by_channel = {}
    for p in all_programs:
        programs_by_channel.setdefault(p['channel_id'], []).append(p)

    # We generate a full 7-day schedule for each channel
    today = datetime.now().date()
    
    for chan_id, programs_data in programs_by_channel.items():
        
        # Create a list of all program instances over the 7-day period
        dated_programs = []
        for i in range(7): # Generate 7 days of schedule
            current_date = today + timedelta(days=i)
            current_day_name = current_date.strftime('%A').upper()
            
            # Filter the static schedule for the current day
            daily_schedule = [p for p in programs_data if p['day'] == current_day_name]
            
            for p in daily_schedule:
                hour, minute = parse_time_to_24h(p['time_str'])
                if hour is not None:
                    # Combine date and time
                    start_dt = datetime(current_date.year, current_date.month, current_date.day, hour, minute)
                    dated_programs.append({
                        'start_dt': start_dt,
                        'title': p['title'],
                        'channel_id': chan_id
                    })

        # Sort all dated programs chronologically for the channel
        dated_programs.sort(key=lambda x: x['start_dt'])
        
        # Now iterate through the sorted list to calculate stop times and create XML
        for i, program in enumerate(dated_programs):
            start_dt = program['start_dt']
            
            # Determine end time: It's the start time of the *next* program.
            if i + 1 < len(dated_programs):
                stop_dt = dated_programs[i+1]['start_dt']
            else:
                # If it's the very last program in the 7-day window, assume a 1-hour duration.
                # This is a fallback and can be adjusted if program durations are known.
                stop_dt = start_dt + timedelta(hours=1)


            # Create the <programme> element
            programme = ET.SubElement(tv, 'programme', attrib={
                'start': start_dt.strftime(XMLTV_TIME_FORMAT),
                'stop': stop_dt.strftime(XMLTV_TIME_FORMAT),
                'channel': program['channel_id']
            })

            # Add <title>
            title = ET.SubElement(programme, 'title', attrib={'lang': 'en'})
            title.text = program['title'].strip()
            
            # Optional: Add a simple <desc> (description)
            desc = ET.SubElement(programme, 'desc', attrib={'lang': 'en'})
            desc.text = program['title'].strip()

    # Create a clean XML string (Pretty print requires Python 3.9+)
    try:
        ET.indent(tv, space="  ")
    except AttributeError:
        # Fallback for older Python versions
        pass 
        
    xml_string = ET.tostring(tv, encoding='utf-8', xml_declaration=True).decode()
    
    # XMLTV standard requires a DTD declaration
    doctype = '<!DOCTYPE tv SYSTEM "xmltv.dtd">'
    return xml_string.replace('<?xml version=\'1.0\' encoding=\'utf-8\'?>', f'<?xml version="1.0" encoding="utf-8"?>\n{doctype}')


# Main execution block
def main():
    all_programs = []
    
    # Get all .txt files in the current directory and process them
    for filename in os.listdir('.'):
        filename_lower = filename.lower()
        if filename_lower in CHANNEL_MAP:
            channel_id = CHANNEL_MAP[filename_lower]
            print(f"Parsing file: {filename} for channel: {channel_id}")
            try:
                programs = parse_schedule_file(filename, channel_id)
                all_programs.extend(programs)
            except Exception as e:
                print(f"Error parsing {filename}: {e}")

    if not all_programs:
        print("No programs found. Exiting.")
        return

    xmltv_content = generate_xmltv(all_programs)
    
    # Write the output file
    output_filename = 'epg.xml'
    with open(output_filename, 'w', encoding='utf-8') as f:
        f.write(xmltv_content)
        
    print(f"\nSuccessfully generated {output_filename} containing {len(all_programs)} base program entries over 7 days.")

if __name__ == '__main__':
    main()
