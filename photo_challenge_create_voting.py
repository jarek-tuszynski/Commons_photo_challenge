'''
    Purpose:  Code to create voting pages for Wikimedia Commons Photo Challenge
    Author:   Jarek Tuszynski [[User:Jarekt]], 2025
    Based on: C# code by [[user:Colin]] (https://commons.wikimedia.org/wiki/Commons:Photo_challenge/code/CreateVoting.cs)
    License:  Public domain
'''

import pywikibot
import re
import datetime
import numpy as np
import pandas as pd
import requests
import math
import os

#=====================================================================================
def get_challenges() -> list:
    ''' Parse [[Commons:Photo challenge/Submitting]] to get names of photo challenges this month
    '''
    site = pywikibot.Site("commons", "commons")  # Wikimedia Commons
    page = pywikibot.Page(site, "Commons:Photo challenge/Submitting")
    text = page.get()  # full wikitext
    text = re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)
    challenge_list = re.findall(r"\{\{Commons:Photo challenge/([^}]+)\}\}", text)
    return challenge_list

#=====================================================================================
def get_file_list(wiki_text: str):
    ''' Parse submition pages of individual challenges to get list of submitted files
    '''
    files = []
    seeking_gallery = True
    challenge_name = ''

    for line in wiki_text.splitlines():
        line = line.strip()
        #print(line)
        if seeking_gallery:
            match = re.search(r"^===\s+(.*?)\s+===", line)
            if match:
                challenge_name = match.group(1)
            if line.startswith("<gallery ") and "250px" in line:
                seeking_gallery = False
        else:
            if line.startswith("<!--") or line.strip() == "":
                continue
            if line.startswith("</gallery>"):
                break

            line = re.sub(re.escape('|thumb'), "", line, flags=re.IGNORECASE)
            line = line.replace('[[','').replace(']]','')

            bar = line.find("|")
            if bar>=0:
                fname = line[:bar]
                title = line[bar + 1:].strip()
            else:
                fname = line
                title = "" 
            fname = re.sub(r'^file:', '', fname, flags=re.IGNORECASE) # Removes "file:" from the beginning of a string
            fname = fname.replace("_", " ")

            if len(title)==0:
                dot = fname.rfind(".")
                title = fname if dot == -1 else fname[:dot]

            if fname == "CLICK HERE To submit your photos to the challenge.svg":
                continue
            files.append([fname, title])
            
    file_df = pd.DataFrame(files, columns=['file_name', 'title'])
    return file_df, challenge_name

#=====================================================================================
def get_file_info(site, file_df, error_fp):
    ''' For each file look up basic info
    '''
    for col in ['user', 'uploaded', 'width', 'height','comment']:
        file_df[col] = None
    for irow, row in file_df.iterrows():
        file_name = row['file_name'].replace(" ", "_")
        file_page = pywikibot.FilePage(site, file_name)
        if not file_page.exists():
            error_fp.write(f'File "{file_name}" does not exist')
            continue
        meta = file_page.oldest_file_info
        text = file_page.get().lower()
        own_work = ('own work' in meta['comment']) or ('{{own}}' in text)  or ('{{sf}}' in text)
        own_work = own_work or ('{{own photo}}' in text)  or ('{{self-photographed}}' in text)
        file_df.loc[irow, 'user']     = meta['user']
        file_df.loc[irow, 'uploaded'] = meta['timestamp']
        file_df.loc[irow, 'width']    = meta['width']
        file_df.loc[irow, 'height']   = meta['height']
        file_df.loc[irow, 'comment']  = meta['comment'] 
        file_df.loc[irow, 'own_work'] = own_work 
        if not own_work:
            error_fp.write(f'[[File:{file_name}]] might not be own work\n')
            continue
        
    return file_df

#=====================================================================================
def create_vote_page(file_name, file_df, error_fp, theme, min_upload_date):
    ''' Create text of the voting page
    '''
    max_upload_date = min_upload_date + datetime.timedelta(days=30, hours=12)
    close_time      = max_upload_date - datetime.timedelta(days=1)
    vote_close_time = max_upload_date + datetime.timedelta(days=30)
    size_px = 240000
    collapse_text = '{{Collapse top|Current votes – please choose your own winners before looking}}\n'
    errors = []

    print('min_upload_date', min_upload_date)
    print('max_upload_date', max_upload_date)
    print('close_time', close_time)
    print('vote_close_time', vote_close_time)

    min_upload_str = min_upload_date.strftime("%d %B %Y")
    max_upload_str = max_upload_date.strftime("%d %B %Y")
    ifile = 1
    with open(file_name, "w", encoding="utf-8") as fp:
        fp.write("__NOTOC__\n")
        fp.write("\n'''Voting will end at midnight UTC on {:%d %B %Y}'''. The theme was '''{}'''.\n\n".format(
            vote_close_time, theme))
        fp.write("{{Commons:Photo challenge/Voting header/{{SuperFallback|Commons:Photo challenge/Voting header}}}}\n")
        fp.write("{{Commons:Photo challenge/Voting example}}\n\n")

        for _, file in file_df.iterrows():
            user  = f'[[User:{file['user']}|{file['user']}]]'
            date  = file['uploaded']
            fname = file['file_name']
            date_str = date.strftime("%d %B %Y")
            error = ''
            if date and date < min_upload_date:
                error = f"REMOVED: [[:File:{fname}]] by {user} was uploaded {date_str} before the challenge opened {min_upload_str}."

            if date and date >= max_upload_date:
                error = f"REMOVED: [[:File:{fname}]] by {user} was uploaded {date_str} after the challenge closed {max_upload_str}."

            if not file['active']:
                error = f"REMOVED: [[:File:{fname}]] by {user}, since the user uploded more than allowed 4 entries."
                
            if len(error)>0:
                errors.append(error)
                continue
                
            w     = file['width'] 
            h     = file['height']
            thumb_width  = int(math.sqrt(size_px * w / h))
            user_text = f"<!-- '''Creator:''' {user} --> "
            date_text = f"'''Uploaded:''' {date_str} "
            size_text = "'''Size''': {} × {} ({} MP) ".format(w, h, w*h/1e6)
            file_link = f"[{{{{filepath:{fname}}}}}<br>''(Full size image)'']"
            num = f'<span class="anchor" id="{ifile}">{ifile}</span>'
            
            fp.write("==={}. {}===\n".format(num, os.path.basename(fname)))
            fp.write("[[File:{}|none|thumb|{}px|{} {}]]\n".format(fname, thumb_width, file['title'], file_link))
            fp.write(user_text+date_text+size_text+collapse_text)
            fp.write("<!-- Vote below this line -->\n")
            fp.write("<!-- Vote above this line -->\n")
            fp.write("{{Collapse bottom}}\n\n")
            ifile += 1

        if len(errors)>0:
            fp.write(('=== Issues corrected by the [[Commons:Photo challenge/code/create voting.py|software]] ===\n'))
            
        for error in errors:
            fp.write("* " + error + "\n")     


#=====================================================================================
def process_challenge(challenge: str):
    ''' Process a single challenge: parse submision page and create voting page
    '''
    # Parse challenge string for dates
    parts    = challenge.split(" - ")
    theme    = parts[2] 
    min_upload_date = datetime.datetime.strptime("1 {} {}".format(parts[1], parts[0]), "%d %B %Y")

    vote_file  = f"{challenge}_voting.txt"
    error_file = f"{challenge}_error.txt"
    error_fp   = open(error_file, "w")

    # Parse Commons:Photo_challenge submission page
    site = pywikibot.Site("commons", "commons")  # Wikimedia Commons
    page = pywikibot.Page(site, 'Commons:Photo challenge/' + challenge)
    if not page:
        error_fp.write(f"Can't open [[Commons:Photo challenge/{challenge}]]\n")
        error_fp.close()
        return

    wiki_text = page.get()
    df, challenge_name = get_file_list(wiki_text)

    # get info for all the files and create voting page
    print('get file info')
    df = get_file_info(site, df, error_fp)

    # enforce only 4 entries per user
    df['active'] = False
    idx = df.groupby("user").head(4).index
    df.loc[idx, "active"] = True
    df = df.sort_values(by='uploaded').sort_values(by='active')
    
    df.to_csv("file_info.csv", index=False)

    print('create_vote_page')
    create_vote_page(vote_file, df, error_fp, theme, min_upload_date)

    error_fp.close()
    return challenge_name

#=====================================================================================
def main():
    #challenge_list = get_challenges()
    challenge_list = ['2025 - September - Bricks','2025 - September - Gold']
    n = len(challenge_list)
    challenge_name = [""] * n
    for i in range(n):
        challenge = challenge_list[i]
        print(challenge)
        challenge_name[i] = process_challenge(challenge)

    # Create text of [[Commons:Photo challenge/Voting]]
    part  = challenge.split(" - ")
    year  = part[0]
    month = datetime.datetime.strptime(part[1], "%B").strftime("%m")
    header = '=== {{ucfirst:{{ISOdate|' + year + '-' + month + '|{{PAGELANGUAGE}}}}}} ==='
    print(header)
    for i in range(n):
        clink = challenge_list[i]
        cname = challenge_name[i].replace('|capitalization=ucfirst}}', '|capitalization=ucfirst|link=-}}')
        print(f'*; [[Commons:Photo challenge/{clink}/Voting|{cname}]]')
        
#=====================================================================================
if __name__ == "__main__":
    main()
