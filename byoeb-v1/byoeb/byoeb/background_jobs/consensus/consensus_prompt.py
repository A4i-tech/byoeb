consensus_prompt = """
###Task Description:
A question ("q") asked by an Accredited Social Health Activist (ASHA) has been answered by multiple Auxiliary Nurse Midwives (ANMs) ("anm_answers"). Your task is to synthesise facts and clarifications in anm_answers into a simple and comprehensive answer ("consensus_answer"), by first identifying any conflicting information in anm_answers and providing a count ("anm_votes"), and second generating a precise explanation ("consensus_explanation").

###Steps:
1. Read q and anm_answers carefully.
2. Identify information within anm_answers relevant to q. Identify the exact count of ANMs whose answers include relevant information.
3a. If the count is 0: (A) Provide an empty string for anm_votes. (B) Provide only "Consensus not reached." as consensus_answer.
3b. Else, ignore all irrelevant information or smalltalk, and identify whether there is conflicting information among anm_answers, i.e., numerical or qualitative details that cannot be simultaneously true.
3b.i. If there are no conflicts: (A) Provide an empty string for anm_votes. (B) Provide consensus_explanation. (C) Provide consensus_answer.
3b.ii. Else, if there are one or more conflicts: (A) Identify the number of conflicts. (B) For each conflict, provide the exact count of ANMs supporting each of the different information (not just the range of answers, or the information provided by a majority of ANMs) in anm_votes. If a single ANM response contains the same information multiple times, count it as only one vote. (C) Use this Python function ‘majority_voting(anm_votes)’ to count if the number of votes among ANMs resulted in a voting majority or not.
def majority_voting(anm_votes):
    results = {}
    for conflict, votes in anm_votes.items():
        # Convert the vote counts from strings to integers
        votes = {key: int(value) for key, value in votes.items()}
        # Find the maximum number of votes received
        max_votes = max(votes.values())
        # Check how many pieces of information have the maximum vote count
        max_vote_keys = [key for key, value in votes.items() if value == max_votes]
        if len(max_vote_keys) == 1:
            # If one piece of information has the highest count, it's the majority
            results[conflict] = "Voting majority"
        else:
            # If there's a tie, indicate no voting majority
            results[conflict] = "No voting majority"
    return results
 3b.ii.1. If there is ‘No voting majority’ (i.e., if there is a tie in votes) for one or more conflicts: (A) Provide consensus_explanation. (B) Provide only "Consensus not reached." as consensus_answer.
3b.ii.2. Else, if there is 'Voting majority' for all conflicts: (A) For each conflict, identify the information provided by a majority of ANMs. (B) Provide consensus_explanation. (C) For each conflict, integrate only that majority information into consensus_answer. Do not mention minority information or conflicts in consensus_answer.

###Instructions:
1. Only use information in anm_answers to generate consensus_answer. Do not use any other source.
2. Strictly follow the JSON output format in the examples. Do not generate any other (opening or closing) explanations or code.
3. Your output (anm_votes, consensus_explanation, and consensus_answer) must only be in English. The input (q and anm_answers) can be in Hindi, English, or Hinglish.
4. consensus_answer must explain information in simple terms without using medical jargon or uncommon words. 
5. consensus_answer must be as short as possible.
6. consensus_answer must be framed as an answer for ASHA workers, who are not patients themselves. 
7. consensus_explanation must only be 1-2 sentences long.
8. Do not allow the length of the ANM answers to influence your output.
9. Be as objective as possible.
10. Make sure you read and understand these instructions carefully.
11. Keep this document open while reviewing, and refer to it as needed.
12. Think step-by-step.

###Examples:

##Example 1:

#Input:
{
"q": "माला एन की टेबलेट कैसे इस्तेमाल करें?",
"anm_answers": ["यहां गर्भ निरोधक गोलियां होती है जिसमें 21 गोली सफेद रंग की एवं 7 गोली काले रंग की होती है टोटल 28 गोली होती है प्रथम बार शुरू करते समय महावारी के पांचवें दिन से स्टार्ट करनी है और बिना किसी रुकावट के प्रत्येक दिन निर्धारित समय पर ही गोली लेनी है अगर किसी दिन गोली लेना भूल जाए तो जैसे ही याद आता है तुरंत गोली लेना है स्टार्ट की तरफ से गोली स्टार्ट करनी है और एक पत्ता खत्म होते ही दूसरा स्टार्ट करना है गोली को बच्चों से दूर रखना है", "यह एक सुरक्षित गर्भ निरोधक साधन है, पिरयड आने कै पांचवे दिन से शुरू करते है हर रोज एक गोली खानी ह", "haa", "Daily ek goli", "Mala N ke tab.mahila ke period ke 5ve din par lene h, Ansar shi h kiya", "Mala and tablet MC ke paanchvein din se tablet Ke Piche Teer ka Nishan se chalu karni hai Lal tablet MC ke Samay per leni hai", "Per Day 1 tablet"]
}


#Output:
{
"anm_votes": "",
"consensus_explanation": "This answer synthesises the unanimous guidance provided by ANMs on the correct usage of Mala N tablets, focusing on starting the cycle, daily intake, and handling missed doses. As the information given by ANMs was qualitativey different but could be simultaneously true, there was no conflicting information and counting votes and identifying the majority was not required.",
"consensus_answer": "Mala N tablets should be started on the fifth day of the menstrual cycle. The pack contains 28 pills, with 21 white and 7 black pills. One pill should be taken daily at the same time without any interruption. If a pill is missed, take it as soon as you remember. After finishing one pack, start the next pack immediately. Keep the pills out of reach of children."
}

##Example 2:

#Input:
{
"q": "HIV walo ko pension milti h kya?",
"anm_answers": ["No", "Yes", "haa", "5 लाख तक का इलाज सरकारी या प्राइवेट हॉस्पिटलो मे निशुल्क किया जायेगा", "Han ji"]
}

#Output:
{
"anm_votes": {"Pension": {"No": "1", "Yes: "3" }},
"consensus_explanation": "The majority of responses indicate that individuals living with HIV do receive pensions. The information about free treatment provides additional support and is included as part of the comprehensive answer.",
"consensus_answer": "People living with HIV are eligible for pensions and can receive free treatment up to ₹5 lakh in government or private hospitals."
}

##Example 3:

#Input:
{
"q": "How much money will we get for nasbandi and when we will get it?",
"anm_answers": ["Under the Janani Suraksha Yojana, ASHA workers will receive ₹600 for transport and other costs when they help women at the hospital. In 2 months you will get.", "1 महीने में सात सौ रुपये सर🙏🏽", "haan 600 in 2 months", "ASHA will get 600 rs for ur travel and other costs when you stay with women at the hospital.", "600 In 1 month"]
}

#Output:
{
"anm_votes": {"Money for sterilisation": {"₹700": "1","₹600": "4"}, "When they would get it": {"1 month": "2", "2 months": "2" }}, 
"consensus_explanation": "There was confusion among ANM responses regarding the amount and timing of payments for sterilisation support. Although a majority of ANMs agreed that ASH workers will receive support of ₹600 for their travel and other costs, however variation in the timeframe for receiving the payment (1 month vs. 2 months) prevented a unified answer.",
"consensus_answer": "Consensus not reached."
}"""