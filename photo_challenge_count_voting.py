import pywikibot
import re
import datetime
import numpy as np
import pandas as pd
import requests
import math
import os

#=====================================================================================
def substr(pattern, text):
    ''' Extract a single substring using regex command '''
    res = ''
    match = re.search(pattern, text)
    if match:
        res = match.group(1).strip()
    return res
    
#=====================================================================================
def get_challenges():
    ''' Inspect "Commons:Photo challenge/Voting" to get names of last month challenges '''
    site = pywikibot.Site("commons", "commons")  # Wikimedia Commons
    page = pywikibot.Page(site, "Commons:Photo challenge/Voting")
    text = page.get()  # full wikitext
    text = re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)
    header = substr(r"(===\s+.+\s+===)", text)
    challenge_list = re.findall(r"Commons:Photo challenge/([^/]+)/Voting", text)
    return header, challenge_list

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
            num   = substr(r"===(\d*)\.", line)
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
        for line in wiki_text.splitlines():
            if line.startswith("<!-- '''Creator"):
                line = line.replace("<!-- ", "").replace(" -->", "").replace(cstr, '')
            elif line.startswith("{{Collapse bottom}}"):
                continue
            elif line.startswith("'''Voting will end"):
                line = line.replace("Voting will end", "Voting ended")
            fp.write(line+'\n')

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
    voter_df.to_csv("voters.csv", index=False)
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
    errors = ['=== Issues corrected by the software ===']
    
    # Report user based issues
    df = voter_df.sort_values(by="error", ascending=True)
    df = df[df['error']>0]
    for _, row in df.iterrows():
        user = f'* ({row['error']}) [[User:{row['voter']}]] '
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
                error = f'* ({row['error']}) [[User:{row['voter']}]] voted more than once for {image} 🡆 subsequent votes were not counted'
            case 6:  # Report unsigned votes
                error = f'* ({row['error']}) Unsigned vote for {image} was detected 🡆 it was not counted (line was: "{row['line']}")'
            case 7: # Report self voting
                error = f'* ({row['error']}) {user} voted for their own {image} 🡆 their vote was not counted'
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
def registration(user)
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

        # text to be added to user's talk pages:
        color= ['', 'Gold', 'Silver', 'Bronze']
        for i in range(10):
            rank  = int(file_df.iloc[i]["rank"])
            if rank>3:
                continue
            fname =     file_df.iloc[i]["file_name"]
            fp.write("Add to [[User talk:{}]] talk page:\n".format(file_df.iloc[i]["creator"]))
            fp.write(f"Header: === [[Commons:Photo challenge/{challenge}/Winners]] ===\n")
            fp.write("{{{{Photo Challenge {}|File:{}|{}|{}|{}}}}}\n\n".format(
                color[rank], fname, theme, year, month))

        # text to be added to announcments
        fp.write(f"== [[Commons:Photo challenge|Photo challenge]] {month} results ==\n")
        fp.write("Congratulations to [[User:{}|]], [[User:{}|]] and [[User:{}|]]. -- ~~~~\n".format(
             file_df.iloc[0]["creator"], 
             file_df.iloc[1]["creator"], 
             file_df.iloc[2]["creator"]))

        # text for [[Commons:Photo challenge/Previous]]
        part  = challenge.split(" - ")
        year  = part[0]
        month = datetime.datetime.strptime(part[1], "%B").strftime("%m")
        header = '=== {{ucfirst:{{ISOdate|' + year + '-' + month + '|{{PAGELANGUAGE}}}}}} ==='
        print(header)
        print(f";* [[Commons:Photo challenge/{challenge}/Voting|{challenge}]] "
              f"-> {{{{Commons:Photo challenge/{challenge}/Winners}}}}")

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
    vote_df.to_csv("votes.csv", index=False)

    file_df = count_votes(vote_df, file_df)
    file_df.to_csv("files.csv", index=False)
    
    errors = list_errors(vote_df, voter_df, challenge)

    # revise voting page and create result page
    revise_voting_page(wiki_text, revised_file)
    create_winners_page(file_df, winners_file, challenge)

    # create result page
    n_voter = vote_df['voter'].nunique()
    create_result_page(file_df, n_voter, result_file, errors)
    
#=====================================================================================
def main():
    #process_challenge('2025 - August - Test')
    #process_challenge('2025 - July - Waterside structures')
    process_challenge('2025 - August - Bark')
    return
    header, challenge_list = get_challenges()
    n = len(challenge_list)
    challenge_name = [""] * n
    print(header)
    for i in range(n):
        challenge = challenge_list[i]
        challenge_name[i] = process_challenge(challenge)
        print(f";* [[Commons:Photo challenge/{challenge}/Voting|{challenge}]] "
              f"-> {{{{Commons:Photo challenge/{challenge}/Winners}}}}")
        return
        
#=====================================================================================
if __name__ == "__main__":
    main()
