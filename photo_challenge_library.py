'''
    Purpose:  Code to create and count voting pages for Wikimedia Commons Photo Challenge
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
# === Create voting pages
#=====================================================================================

def copy_commons_page(source_title = 'Commons:Photo challenge/Submitting' , 
                      target_title = 'Commons:Photo challenge/Submitting_old'):
    '''copy content of Wikimedia Commons "Commons:Photo challenge/Submitting" page to 
       "Commons:Photo challenge/Submitting_old" '''
    # Connect to Wikimedia Commons
    site = pywikibot.Site('commons', 'commons')
    
    # Get source page
    source_page = pywikibot.Page(site, source_title)
    target_page = pywikibot.Page(site, target_title)
    
    # Save content to target page with edit summary
    target_page.text = source_page.text
    target_page.save(summary=f'Copied from [[{source_title}]]')

#=====================================================================================
def get_submitted_challenges(source_title = 'Commons:Photo challenge/Submitting') -> list:
    ''' Parse [[Commons:Photo challenge/Submitting]] to get names of photo challenges this month
    '''
    site = pywikibot.Site("commons", "commons")  # Wikimedia Commons
    page = pywikibot.Page(site, source_title)
    text = page.get()  # full wikitext
    text = re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)
    challenge_list = re.findall(r"\{\{Commons:Photo challenge/([^}]+)\}\}", text)
    return challenge_list

#=====================================================================================
def parse_submition_page(wiki_text: str):
    ''' Parse submition page of individual challenge to get list of submitted files
    '''
    files = []
    seeking_gallery = True

    for line in wiki_text.splitlines():
        line = line.strip()
        #print(line)
        if seeking_gallery:
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
    return file_df

#=====================================================================================
def get_file_info(site, file_df):
    ''' For each file look up basic info
    '''
    for col in ['user', 'uploaded', 'width', 'height','comment']:
        file_df[col] = None
    for irow, row in file_df.iterrows():
        file_name = row['file_name'].replace(" ", "_")
        file_page = pywikibot.FilePage(site, file_name)
        if not file_page.exists():
            print(f'File "{file_name}" does not exist')
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
            print(f'[[File:{file_name}]] might not be own work\n')
        
    return file_df

#=====================================================================================
def create_voting_page(challenge: str, file_df):
    ''' Create text of the voting page
    '''
    # Parse challenge string for dates
    parts    = challenge.split(" - ")
    theme    = parts[2] 
    min_upload_date = datetime.datetime.strptime("1 {} {}".format(parts[1], parts[0]), "%d %B %Y")
    file_name = f"{challenge}_voting.txt"

    max_upload_date = (min_upload_date + datetime.timedelta(days=31, hours=12)).replace(day=1)
    close_time      =  max_upload_date - datetime.timedelta(days=1)
    vote_close_time = (max_upload_date + datetime.timedelta(days=31)).replace(day=1)
    size_px = 240000
    collapse_text = '{{Collapse top|Current votes – please choose your own winners before looking}}\n'
    errors = []

    print('min_upload_date', min_upload_date)
    print('max_upload_date', max_upload_date)
    print('close_time', close_time)
    print('vote_close_time', vote_close_time)

    min_upload_str = min_upload_date.strftime("%Y-%m-%d %H:%M:%S")
    max_upload_str = max_upload_date.strftime("%Y-%m-%d %H:%M:%S")
    with open(file_name, "w", encoding="utf-8") as fp:
        fp.write("__NOTOC__\n")
        fp.write("\n'''Voting will end at midnight UTC on {:%d %B %Y}'''. The theme was '''{}'''.\n\n".format(
            vote_close_time, theme))
        fp.write("{{Commons:Photo challenge/Voting header/{{SuperFallback|Commons:Photo challenge/Voting header}}}}\n")
        fp.write("{{Commons:Photo challenge/Voting example}}\n\n")

        ifile = 0
        for _, file in file_df.iterrows():
            user  = f'[[User:{file['user']}|{file['user']}]]'
            date  = file['uploaded']
            fname = file['file_name']
            if (user is None) or (date is None) or (fname is None):
                error = f"File [[:File:{fname}]] does not exist"
                errors.append(error)
                continue
                
            date_str = date.strftime("%Y-%m-%d %H:%M:%S")
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
                
            w = file['width'] 
            h = file['height']
            ifile += 1
            thumb_width = int(math.sqrt(size_px * w / h))
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

        if len(errors)>0:
            fp.write(('=== Issues corrected by the [[Commons:Photo challenge/code/create voting.py|software]] ===\n'))
            print("Issues:")
            
        for error in errors:
            fp.write("* " + error + "\n")
            print("* " + error + "\n")     

#=====================================================================================
def create_voting_page_from_submission_page(challenge: str):
    ''' Process a single challenge: parse submision page and create voting page
    '''
    files_file = f"{challenge}_submission_files.csv"
    site = pywikibot.Site("commons", "commons")  # Wikimedia Commons
    # Parse Commons:Photo_challenge submission page
    page = pywikibot.Page(site, 'Commons:Photo challenge/' + challenge)
    if not page:
        print(f"Error: Can't open [[Commons:Photo challenge/{challenge}]]\n")
        return

    file_df = parse_submition_page(page.get())

    # get info for all the files
    file_df = get_file_info(site, file_df)

    # enforce only 4 entries per user
    file_df['active'] = False
    idx = file_df.groupby("user").head(4).index
    file_df.loc[idx, "active"] = True

    # sort by upload date
    file_df = file_df.sort_values(by='uploaded').sort_values(by='active').reset_index(drop=True)
    file_df.to_csv(files_file, index=True)
    
    print('create voting page')
    create_voting_page(challenge, file_df)

    return file_df

#=====================================================================================
def get_new_text_of_voting_index(challenge_list: list):
    # Create new text for [[Commons:Photo challenge/Voting]]
    site  = pywikibot.Site("commons", "commons")  # Wikimedia Commons
    year, month, theme = challenge.split(" - ")
    month  = datetime.datetime.strptime(month, "%B").strftime("%m")
    header = f'=== {{{{ucfirst:{{{{ISOdate|{year}-{month}|{{{{PAGELANGUAGE}}}}}}}}}}}} ==='
    print(header)
    for challenge in challenge_list:
        page = pywikibot.Page(site, 'Commons:Photo challenge/' + challenge)
        if page:     
            wiki_text = page.get()
            for line in wiki_text.splitlines():
                line = line.strip()
                match = re.search(r"^===\s+(.*?)\s+===", line)
                if match:
                    challenge_code = match.group(1)
                    challenge_code = challenge_code.replace('|capitalization=ucfirst}}', '|capitalization=ucfirst|link=-}}')
                    print(f'* [[Commons:Photo challenge/{challenge}/Voting|{challenge_code}]]')

#=====================================================================================
# === Count voting pages
#=====================================================================================

def substr(pattern, text):
    ''' Extract a single substring using regex command '''
    res = ''
    match = re.search(pattern, text)
    if match:
        res = match.group(1).strip()
    return res
    
#=====================================================================================
def get_voting_challenges(page_name = "Commons:Photo challenge/Voting"):
    ''' Inspect "Commons:Photo challenge/Voting" to get names of last month challenges '''
    site = pywikibot.Site("commons", "commons")  # Wikimedia Commons
    page = pywikibot.Page(site, page_name)
    text = page.get()  # full wikitext
    text = re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)
    header = substr(r"(===\s+.+\s+===)", text)
    challenge_list = re.findall(r"Commons:Photo challenge/([^/]+)/Voting", text)
    return challenge_list

#=====================================================================================
def parse_voting_page(wiki_text: str):
    ''' Load voting page and extract information about all the files and all the votes'''
    files = []
    votes = []
    points = [0,3,2,1]

    for line in wiki_text.splitlines():
        line = line.strip()

        # Section marker === ... ===
        if line.startswith("==="):
            #num   = substr(r"===(\d*)\.", line)  #===<span class="anchor" id="2">2</span>
            num   = substr(r'<span[^>]*>(\d+)</span>', line)  #===<span class="anchor" id="2">2</span>
            fname = ''
            title = ''
            creator = ''
            voter = ''

        # File lines
        if "[[File:" in line:
            part  = line.replace("[[File:", "").replace("[", "|").split("|")
            fname = part[0].strip()
            if len(part) >= 5:
                title = part[4].strip()
            continue

        # Creator
        if line.startswith("<!-- '''C") or line.startswith("'''C"):
            creator = substr(r"\[\[User:([^|]+)", line)
            files.append([num, fname, title, creator])
            continue

        # Votes
        if "*}}" in line and fname != 'Sample-image.svg':
            #voter = substr(r"\[\[(?::?\w:)?(?:\w{2}:)(?:[Uu]ser|[Bb]enutzer|[Uu]suario):([^|\]]+)", line)
            if '[[Special:Contributions/' in line:
                voter = substr(r"\[\[Special:Contributions/([^|\]]+)", line)
            else:
                voter = substr(r"\[\[(?:[Uu]ser|[Bb]enutzer|[Uu]suario):([^|\]]+)", line)
            award = substr(r"{{(\d)/3\*}}", line)
            line  = line.replace('<span class="signature-talk">{{int:Talkpagelinktext}}</span>','')
            if len(award)>0:
                votes.append([num, int(award), voter, creator, line])
                
    file_df = pd.DataFrame(files, columns=['num', 'file_name', 'title', 'creator'])
    vote_df = pd.DataFrame(votes, columns=['num', 'award', 'voter', 'creator', 'line'])
    return file_df, vote_df

#=====================================================================================
def parse_voting_page1(wiki_text: str):
    ''' Load voting page and extract information about all the files and all the votes'''
    files = []
    votes = []
    points = [0,3,2,1]

    for line in wiki_text.splitlines():
        line = line.strip()

        # Section marker === ... ===
        if line.startswith("==="):
            num   = substr(r"===+(\d*)\.", line)
            fname = ''
            title = ''
            creator = ''
            voter = ''

        # File lines
        if "[[File:" in line:
            part  = line.replace("[[File:", "").replace("[", "|").split("|")
            fname = part[0].strip()
            if len(part) >= 5:
                title = part[4].strip()
            continue

        # Creator
        if line.startswith("<!-- '''C") or line.startswith("'''C"):
            creator = substr(r"\[\[User:([^|]+)", line)
            files.append([num, fname, title, creator])
            continue

        # Votes
        if "*}}" in line and fname != 'Sample-image.svg':
            #voter = substr(r"\[\[(?::?\w:)?(?:\w{2}:)(?:[Uu]ser|[Bb]enutzer|[Uu]suario):([^|\]]+)", line)
            if '[[Special:Contributions/' in line:
                voter = substr(r"\[\[Special:Contributions/([^|\]]+)", line)
            else:
                voter = substr(r"\[\[(?:[Uu]ser|[Bb]enutzer|[Uu]suario):([^|\]]+)", line)
            award = substr(r"{{(\d)/3\*}}", line)
            line  = line.replace('<span class="signature-talk">{{int:Talkpagelinktext}}</span>','')
            if len(award)>0:
                votes.append([num, int(award), voter, creator, line])
                
    file_df = pd.DataFrame(files, columns=['num', 'file_name', 'title', 'creator'])
    vote_df = pd.DataFrame(votes, columns=['num', 'award', 'voter', 'creator', 'line'])
    return file_df, vote_df

#=====================================================================================
def revise_voting_page(wiki_text: str, file_name: str):
    ''' Alter Voting page after voting ends '''
    cstr = "{{Collapse top|Current votes – please choose your own winners before looking}}"
    with open(file_name, "w", encoding="utf-8") as fp:
        fp.write('{{Discussion top}}')
        for line in wiki_text.splitlines():
            if line.startswith("<!-- '''Creator"):
                line = line.replace("<!-- ", "").replace(" -->", "").replace(cstr, '')
            elif line.startswith("{{Collapse bottom}}"):
                continue
            elif line.startswith("'''Voting will end"):
                line = line.replace("Voting will end", "Voting ended")
            fp.write(line+'\n')
            
        fp.write('{{Discussion bottom}}')

#=====================================================================================
def validate_voters(site, vote_df, challenge):
    ''' Analyze people who voted to verify if they were eligible. The precise wording on 
        each voting page is "Voting is open to all registered contributors who have held 
        accounts for at least 10 days and made 50 edits, and also to new Commons contributors 
        who have entered the challenge with a picture."
    '''
    parts      = challenge.split(" - ")
    start_date = datetime.datetime.strptime("30 {} {}".format(parts[1], parts[0]), "%d %B %Y")
    voter_list = vote_df['voter'].unique()     # get unique voters names
    voter_list = voter_list[voter_list != '']  # remove empty strings
    voter_df   = pd.DataFrame(voter_list, columns = ['voter'])
    voter_df['error'] = 0
    voter_df['note']  = 0
    for irow, row in voter_df.iterrows():
        if re.fullmatch(r"[0-9.]+", row['voter']):
            voter_df.loc[irow, 'error'] = 1 # mark IP adress
            continue
            
        user = pywikibot.User(site, row['voter'])
        edit_count = user.editCount()
        reg_date   = user.registration()
        voter_df.loc[irow, 'edit_count' ] = int(edit_count)
        if user.isRegistered():
            days_active = int((start_date - reg_date).days)
            voter_df.loc[irow, 'reg_date'] = reg_date
            voter_df.loc[irow, 'note']  = 1 if user.is_blocked() else 0
        else:
            voter_df.loc[irow, 'error'] = 2 # mark not registered users
            continue

        error = 'error'
        if days_active<10 or edit_count<50:  
            # "New Commons contributors who have entered the challenge with a picture" are allowed to vote
            for contrib in user.contributions():
                page_name = contrib[0].title()
                if page_name.startswith('Commons:Photo challenge/') and page_name.count('/')==1:
                    error = 'note' # no error
                    
        if days_active<10: voter_df.loc[irow, error] = 3 # mark users registered less than 10 days before begining of voting
        if edit_count<50:  voter_df.loc[irow, error] = 4 # mark users with less than 50 edits

    voter_df['edit_count'] = voter_df['edit_count'].fillna(-1).astype(int)
    voter_df['error']      = voter_df['error'     ].fillna( 0).astype(int) 
    #voter_df.to_csv("voters.csv", index=False)
    return voter_df

#=====================================================================================
def validate_votes(vote_df, voter_df):
    ''' Analyze votes to verify if they were following to rules. The precise wording on 
        each voting page is "Voters who voted for more than one 1st, 2nd or 3rd place 
        will have those votes converted to Highly Commended praises. Other votes not 
        complying with the requirements will be removed." Also: "Users cannot vote for 
        their own picture."
    '''
    # copy disqualifying issues from voter dataframe voter_df to vote_df
    vote_df = vote_df.merge(voter_df[["voter", "error"]], on="voter", how="left")
    # allow disqualified voters to award High Commendations
    vote_df.loc[ (vote_df["award"] == 0) & (vote_df["error"] > 0), 'error'] = 0 
    #vote_df['error'] = vote_df['error'].fillna(-9).astype(int) # make column an integer column

    # mark duplicate votes or a user voting for the same image twice. The second vote will be nullified
    vote_df.loc[vote_df.duplicated(subset=["num", "voter"]), 'error'] = 5 

    # mark unsigned votes
    vote_df.loc[vote_df["voter"]=='', 'error'] = 6 

    # mark instances where image creator voted for their own image
    vote_df.loc[vote_df["voter"]==vote_df["creator"], 'error'] = 7 

    # mark votes by voters who voted for more than one 1st, 2nd or 3rd place. 
    mask1 = (vote_df["award"] > 0) & (vote_df["error"] == 0)
    mask2 = vote_df[mask1].duplicated(subset=["award", "voter"], keep=False)
    #for award in range(1,4):
    #    df = vote_df[(vote_df["award"] == award) & (vote_df["error"] == 0)]
    print('validate_votes 1', mask1.count(), mask1.sum()  ) 
    print('validate_votes 2', mask2.count(), mask2.sum()  ) 

    vote_df.loc[mask1 & mask2, 'error'] = 8 # mark multiple same award by a single user
    return vote_df 

#=====================================================================================
def list_errors(vote_df, voter_df, challenge):
    errors = ['=== Issues corrected by the [[Commons:Photo challenge/code/Photo challenge library.py|software]] ===']
    
    # Report user based issues
    df = voter_df.sort_values(by="error", ascending=True)
    df = df[df['error']>0]
    for _, row in df.iterrows():
        user = f'* [[User:{row['voter']}]] '
        match row['error']:
            case 1: # Report IP adresses
                user  = f'* ({row['error']}) [[Special:Contributions/{row['voter']}|{row['voter']}]] '
                error = f'is an anonymous IP adress'
            case 2: # Report unregistered users
                error = f' is not registered'
            case 3:  # Report users with accounts less then 10 days old
                registered = registration(row['voter'])
                error = (f'*{registered} on {row['reg_date']} which is less then '
                        'required 10 days before voting started')
            case 4:  # Report users with less then required 50 edits
                error = (f'made [[Special:Contributions/{row['voter']}|{row['edit_count']} edits on Commons]], '
                         'which is less then required 50')
        errors.append(user + error +  ' 🡆 their votes were not counted')
        
    # Report voting issues
    df = vote_df.sort_values(by="error", ascending=True)
    df = df[df['error']>0]
    df.to_csv("vote_errors.csv", index=False)

    for _, row in df.iterrows():
        user  = f'[[User:{row['voter']}]]'
        n     = int(row['num'])
        image = f'[[Commons:Photo challenge/{challenge}/Voting#{n}|Image #{n}]]'
        match row['error']:
            case 5: # user voting for the same image twice
                error = f'* [[User:{row['voter']}]] voted more than once for {image} 🡆 subsequent votes were not counted'
            case 6:  # Report unsigned votes
                error = f'* Unsigned vote for {image} was detected 🡆 it was not counted (line was: "{row['line']}")'
            case 7: # Report self voting
                error = f'* {user} voted for their own {image} 🡆 their vote was not counted'
            case _:
                continue
        errors.append(error)        

    # Report multi voting
    voters = vote_df[vote_df['error']==8]['voter'].unique()
    place = ['', '3rd', '2nd', '1st']
    ignore = ' 🡆 those votes were not counted'
    for voter in voters:
        df = vote_df[(vote_df['error']==8) & (vote_df['voter']==voter)]
        for award in range(1,4):
            images = df[df['award']==award]['num']
            if (len(images)==0): continue
            img_str = format_array(images, challenge )
            error = f'* [[User:{voter}]] awarded {place[award]} place to multiple images ({img_str}) {ignore}'  
            errors.append(error)
            
    if len(errors)==1:
        errors.append('* no issues found')
        
    df = voter_df.sort_values(by="note", ascending=True)
    df = df[df['note']>0]
    if len(df)>0:
        errors.append('\n=== Other (potential) Issues ===')
    for _, row in df.iterrows():
        user = f'* [[User:{row['voter']}]] '
        match row['note']:
            case 1:
                error = f'is currently blocked'
            case 3:
                error = f'registered less then 10 days before voting started; however, they have entered the challenge with a picture'
            case 4:
                error = f'[[Special:Contributions/{row['voter']}|made less then required 50 edits]] on Commons; however, they have entered the challenge with a picture'
            case _:
                continue
        errors.append(user + error)
        
    return errors

#=====================================================================================
def registration(user):
   link = f'[https://commons.wikimedia.org/wiki/Special:Log?type=newusers&user={user}|registered]'
   return f'<span class="plainlinks">{link}</span>'

#=====================================================================================
def format_array(vec, challenge ):
    nums = [f'[[Commons:Photo challenge/{challenge}/Voting#{n}|{n}]]' for n in vec]
        
    if len(nums) == 0:
        return ""
    elif len(nums) == 1:
        return nums[0]
    elif len(nums) == 2:
        return " and ".join(nums)
    else:
        return ", ".join(nums[:-1]) + " and " + nums[-1]

#=====================================================================================
def count_votes(vote_df, file_df):
    # score the results. According to the documentation: "The Score is the sum of the 
    # 3*/2*/1* votes. The Support is the count of 3*/2*/1* votes and 0* likes. "
    votes = vote_df[vote_df["error"] >= 0]
    df1 = votes.groupby("num", as_index=False)["award"].sum()
    df2 = votes.groupby("num", as_index=False)["award"].count()
    df1.rename(columns={"award": "score"  }, inplace=True)
    df2.rename(columns={"award": "support"}, inplace=True)
    file_df = file_df.merge(df1, on="num", how="left").merge(df2, on="num", how="left")

    # determine rank which is based on the score, but in the event of a tie vote, the support decides the rank
    max_support = file_df['support'].max() + 1
    file_df['score2'] = file_df['score'] + file_df['support']/max_support
    file_df = file_df.sort_values(by="score2"  , ascending=False)
    file_df["rank"] = file_df['score2'].rank(method="min", ascending=False, numeric_only=True)
    file_df["score"]   = file_df["score"  ].fillna(0).astype(int)
    file_df["support"] = file_df["support"].fillna(0).astype(int)
    file_df["rank"]    = file_df["rank"   ].fillna(0).astype(int)
    return file_df

#=====================================================================================
def create_result_page(file_df, n_voter: int, file_name: str, errors: list):
    ''' Create text of the "Result" page with a table with all the images and their final score
    '''
    n_creator = file_df['creator'].nunique()
    n_images  = file_df['num'].nunique()
    talk_str  = '<span class="signature-talk">{{int:Talkpagelinktext}}</span>'
    with open(file_name, "w", encoding="utf-8") as fp:
        fp.write(f"*Number of contributors: {n_creator}\n")
        fp.write(f"*Number of voters:       {n_voter}\n")
        fp.write(f"*Number of images:       {n_images}\n\n")   
        fp.write("The Score is the sum of the 3*/2*/1* votes. ")   
        fp.write("The Support is the count of 3*/2*/1* votes and 0* likes. I")   
        fp.write("In the event of a tie vote, the support decides the rank.\n\n")   
        fp.write('{| class="sortable wikitable"\n|-\n') 
        fp.write('! class="unsortable"| Image\n') 
        fp.write('! Author\n') 
        fp.write('! data-sort-type="number" | Rank\n') 
        fp.write('! data-sort-type="number" | Score\n') 
        fp.write('! data-sort-type="number" | Support\n') 
        for ifile, file in file_df.iterrows():
            _, fname, _, user, score, support, _, rank = file.tolist()
            if support==0:
                break
            user_str = f'[[User:{user}|{user}]] ([[User talk:{user}|{talk_str}]])'
            fp.write(f'|-\n| [[File:{fname}|120px]] || {user_str} || {rank} || {score} || {support}\n')   
            
        fp.write('|}\n\n')   

        for error in errors:
            fp.write(error + "\n")     

#=====================================================================================
def create_winners_page(file_df, file_name: str, challenge: str):
    ''' Create text of the "Winners" page with [[Template:Photo challenge winners table]]
        listing winners of the photo challenge
    '''
    year, month, theme = challenge.split(" - ")
    with open(file_name, "w", encoding="utf-8") as fp:
        fp.write("{{Photo challenge winners table\n");
        fp.write(f"|page     = Photo challenge/{challenge}\n")
        fp.write(f"|theme    = {theme}\n")
        fp.write( "|height   = {{{height|240}}}\n");
        for i in range(3):
            title = add_line_breaks(file_df.iloc[i]["title"], 40)
            fp.write("|image_{}  = {}\n".format(i+1, file_df.iloc[i]["file_name"]))
            fp.write("|title_{}  = {}\n".format(i+1, title))
            fp.write("|author_{} = {}\n".format(i+1, file_df.iloc[i]["creator"]))
            fp.write("|score_{}  = {}\n".format(i+1, file_df.iloc[i]["score"]))
            fp.write("|rank_{}   = {}\n".format(i+1, file_df.iloc[i]["rank"]))
            fp.write("|num_{}    = {}\n".format(i+1, file_df.iloc[i]["num"]))

        fp.write("}}\n\n")

#=====================================================================================
def talk_to_winners(challenge: str):
    files_file = f"{challenge}_files.csv"
    file_df    = pd.read_csv(files_file)
    site       = pywikibot.Site("commons", "commons")  # Wikimedia Commons

    # text to be added to user's talk pages:
    color= ['', 'Gold', 'Silver', 'Bronze']
    year, month, theme = challenge.split(" - ")
    for i in range(10):
        rank = int(file_df.iloc[i]["rank"])
        if rank>3:
            continue
        fname   = file_df.iloc[i]["file_name"]
        page_title = 'User:' + file_df.iloc[i]["creator"]
        header = f"[[Commons:Photo challenge/{challenge}/Winners]]"
        text   = "{{{{Photo Challenge {}|File:{}|{}|{}|{}}}}}".format(
                  color[rank], fname, theme, year, month)

        talk_page = pywikibot.Page(site, page_title).toggleTalkPage()
        if not talk_page.exists():
            print('Talk page does not exist')
            return

        talk_page.text += f"\n\n== {header} ==\n{text}--~~~~"
        talk_page.save(summary="Announcing Photo Challenge winners")
        
#=====================================================================================
def announce_challenge_winners(challenge_list: list):
    challenge1, challenge2 = challenge_list
    year, month, theme = challenge1.split(" - ")
    header = f"[[Commons:Photo challenge|Photo challenge]] {month} results"
    text1  = f"{{{{Commons:Photo challenge/{challenge1}/Winners|height=240}}}}" 
    text2  = f"{{{{Commons:Photo challenge/{challenge2}/Winners|height=240}}}}" 

    file1_df = pd.read_csv(f"{challenge1}_files.csv")
    file2_df = pd.read_csv(f"{challenge2}_files.csv")
    users = [file1_df.iloc[0]["creator"], file1_df.iloc[1]["creator"], file1_df.iloc[2]["creator"],
             file2_df.iloc[0]["creator"], file2_df.iloc[1]["creator"], file2_df.iloc[2]["creator"]]
    users = [f"[[User:{u}|]]" for u in users]
    text3 = "Congratulations to " + ", ".join(users[:-1]) + " and " + users[-1]
    
    site      = pywikibot.Site("commons", "commons")  # Wikimedia Commons
    talk_page = pywikibot.Page(site, 'Commons:Photo challenge').toggleTalkPage()
    if not talk_page.exists():
        print('Talk page does not exist')
        return

    talk_page.text += f"\n\n== {header} ==\n{text1}\n{text2}\n{text3}--~~~~"
    talk_page.save(summary="Announcing Photo Challenge winners")

#=====================================================================================
def add_assesment_to_files(challenge_list: list):
    site = pywikibot.Site("commons", "commons")  # Wikimedia Commons
    header = "=={{Assessment}}==\n"
    marker1 = "=={{int:license-header}}=="
    marker2 = "|other versions=\n}}\n\n"
    marker3 = "[[Category:"
    for idx, challenge in enumerate(challenge_list):
        year, month, theme = challenge.split(" - ")
        file_df = pd.read_csv(f"{challenge}_files.csv")
        for ifile in range(3):
            file = 'File:' + file_df.iloc[ifile]["file_name"]
            template = f"{{{{Photo challenge winner|{ifile+1}|{theme}|{year}|{month}}}}}\n\n" 
            page = pywikibot.Page(site, file)
            if not page.exists():
                continue
            text = page.text
            if '{{Photo challenge winner' in text:
                continue
            if (marker1 in text):
                before, after = text.split(marker1, 1)
                page.text = before + header + template + marker1 + after
            elif (marker2 in text):
                before, after = text.split(marker2, 1)
                page.text = before + marker2 + header + template + after
            else:
                before, after = text.split(marker3, 1)
                page.text = before + header + template + marker3 + after
                
            page.save(summary="Assessment added - congratulations")
            print('Adding assesment template to ' + file)

#=====================================================================================
def update_previous_page(challenge_list: list):
    # text to be added to Photo Challenge talk page
    challenge1, challenge2 = challenge_list
    year, month_str, theme = challenge1.split(" - ")   
    month  = datetime.datetime.strptime( month_str, "%B").strftime("%m")
    header = f'{{{{ucfirst:{{{{ISOdate|{year}-{month}|{{{{PAGELANGUAGE}}}}}}}}}}}}'
    text1  = f"{{{{Commons:Photo challenge/{challenge1}/Winners}}}}" 
    text2  = f"{{{{Commons:Photo challenge/{challenge2}/Winners}}}}" 
    
    site = pywikibot.Site("commons", "commons")  # Wikimedia Commons
    page = pywikibot.Page(site, 'Commons:Photo challenge/Previous')
    if not page.exists():
        print('Page does not exist')
        return

    page.text = f"=== {header} ===\n{text1}\n{text2}\n\n" + page.text
    page.save(summary=f"Add {month_str} winners")

#=====================================================================================
def add_line_breaks(sentence: str, max_len: int):
    words = sentence.split()
    lines = []
    current_line = []

    current_len = 0
    for word in words:
        if current_len + len(word) + (1 if current_line else 0) <= max_len:
            current_line.append(word)
            current_len += len(word) + (1 if current_line[:-1] else 0)
        else:
            lines.append(" ".join(current_line))
            current_line = [word]
            current_len = len(word)
    if current_line:
        lines.append(" ".join(current_line))

    return ' <br/>'.join(lines)
        
#=====================================================================================
def process_challenge(challenge: str):
    vote_file    = f"{challenge}_voting.txt"
    error_file   = f"{challenge}_error.txt"
    revised_file = f"{challenge}_revised.txt"
    result_file  = f"{challenge}_result.txt"
    winners_file = f"{challenge}_winners.txt"
    votes_file   = f"{challenge}_votes.csv"
    files_file   = f"{challenge}_files.csv"
    error_fp     = open(error_file, "w")

    # Parse Commons:Photo_challenge submission page
    site = pywikibot.Site("commons", "commons")  # Wikimedia Commons
    page = pywikibot.Page(site, f"Commons:Photo challenge/{challenge}/Voting")
    if not page:
        error_fp.write(f"Can't open [[Commons:Photo challenge/{challenge}/Voting]]\n")
        error_fp.close()
        return

    wiki_text = page.get()
    file_df, vote_df= parse_voting_page(wiki_text)

    voter_df = validate_voters(site, vote_df, challenge)
    vote_df  = validate_votes(vote_df, voter_df)
    vote_df.to_csv(votes_file, index=False)

    file_df = count_votes(vote_df, file_df)
    file_df.to_csv(files_file, index=False)
    
    errors = list_errors(vote_df, voter_df, challenge)

    # revise voting page and create result page
    revise_voting_page(wiki_text, revised_file)
    create_winners_page(file_df, winners_file, challenge)

    # create result page
    n_voter = vote_df['voter'].nunique()
    create_result_page(file_df, n_voter, result_file, errors)

#=====================================================================================
def create_commons_page(challenge: str, subpage1: str, subpage2: str):
    '''  '''
    # Connect to Wikimedia Commons
    site = pywikibot.Site('commons', 'commons')
    
    # Get source page
    source_file  = f"{challenge}_{subpage1}.txt"
    with open(source_file, 'r') as file:
        source_text = file.read()
    
    target_title = f"Commons:Photo challenge/{challenge}/{subpage2}"
    target_page  = pywikibot.Page(site, target_title)
    target_title = target_title.replace(' ', '_')
    
    # Save content to target page with edit summary
    target_page.text = source_text
    target_page.save(summary='Generated with photo_challeng_library.py')
    print(f'Created [{target_title}](https://commons.wikimedia.org/wiki/{target_title}')

           
