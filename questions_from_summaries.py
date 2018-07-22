import os, string, pickle, re, argparse, spacy, copy
from time import sleep
from tqdm import tqdm
import math
from textblob import TextBlob as tb

# this can be changed according to the type of entities you are looking for
all_entities = ['PERSON', 'NORP', 'FACILITY', 'ORG', 'GPE', 'LOC', 'PRODUCT', 'EVENT', 'WORK_OF_ART', 'LAW', 'LANGUAGE', 'DATE', 'TIME', 'PERCENT', 'MONEY', 'QUANTITY', 'ORDINAL', 'CARDINAL']

def read_pickle(file):
    with open(file, 'rb') as f:
        data = pickle.loads(f.read())
    return data

def write_pickle(file, data):
    with open(file, 'wb') as f:
        pickle.dump(data, f, protocol=2)

def create_files_mapping(args):
    print('create_files_mapping')
    files_mapping = {}

    for root, dirs, files in os.walk(args.data):
        for file in files:
            prefix = file[:7]
            if prefix not in files_mapping:
                files_mapping[prefix] = {'man': [], 'machine': []}
            if file[-1] in string.ascii_uppercase[:8]:
                files_mapping[prefix]['man'].append(file)
            else:
                files_mapping[prefix]['machine'].append(file)
    for k, v in files_mapping.items():
        if len(v['man']) != 4:
            print(len(v['man']))
        if len(v['machine']) != 51:
            print(len(v['machine']))
    write_pickle(get_file_name(args, 'files_mapping'), files_mapping)

    return files_mapping

def create_entities(args, files_mapping):
    print('create_entities')
    nlp = spacy.load('en')

    entities = {}
    for prefix in tqdm(files_mapping.keys(), total=len(files_mapping)):
        man_made_files = files_mapping[prefix]['man']
        for man_made_file in man_made_files:
            with open(os.path.join(args.data, man_made_file), encoding='cp1252') as file:
                text = file.read()
                text = clean_text(text)
                doc = nlp(text)
                for ent in doc.ents:
                    if ent.label_ in all_entities and ent.end_char - ent.start_char > 1 and len(ent.text.strip()) >= 0:
                        if prefix not in entities:
                            entities[prefix] = {}
                        if man_made_file not in entities[prefix]:
                            entities[prefix][man_made_file] = []
                        if ent.text not in entities[prefix][man_made_file]:
                            entities[prefix][man_made_file].append(ent.text)

    write_pickle(get_file_name(args, 'entities'), entities)

def merge_keywords(args, files_mapping):
    print("merge_keywords")

    nlp = spacy.load('en')
    
    entities = read_pickle(get_file_name(args, 'entities'))
    keywords = {}

    for prefix in tqdm(files_mapping.keys(), total=len(files_mapping)):
        for man_made_file in files_mapping[prefix]['man']:
            if prefix not in entities or man_made_file not in entities[prefix]: continue
            keywords_nominees = entities[prefix][man_made_file]

            if prefix not in keywords:
                keywords[prefix] = {}
            keywords[prefix][man_made_file] = merge(nlp, keywords_nominees)

    write_pickle(get_file_name(args, 'keywords'), keywords)

class Node:

    def __init__(self, entity, lemma_entity, value, parent):
        self.entity = entity
        self.lemma_entity = lemma_entity
        self.value = value
        self.parent = parent

    def print_me(self):
        print(self.entity, self.lemma_entity, self.value, self.parent)


def merge(nlp, keywords_nominees, graph=None):
    if graph==None: graph = []
    sorted_keywords = sorted(set([i.lower().strip('()') for i in keywords_nominees]), key = lambda x: (len(x), x.lower()), reverse=True)
    sorted_keywords_lemmas = [nlp(key)[:].lemma_ for key in sorted_keywords]
    i = 0
    while i < len(sorted_keywords):
        if sorted_keywords[i] in [x.entity for x in graph]: i+=1; continue
        graph_indexing = len(graph)
        graph.append(Node(sorted_keywords[i], sorted_keywords_lemmas[i], len(graph), None))
        j = 0
        while j < len(graph):
            if graph_indexing!=j:
                if (graph[j].lemma_entity == graph[graph_indexing].lemma_entity or re.search(r'\b' + re.escape(graph[graph_indexing].entity) + r'\b', graph[j].entity, flags=re.IGNORECASE) != None or re.search(r'\b' + re.escape(graph[j].entity) + r'\b', graph[graph_indexing].entity, flags=re.IGNORECASE) != None):
                    graph[graph_indexing].parent = j
                    break
            j+=1
        i+=1

    return graph

def graph_to_dict(graph):
    dic = {}
    for x in graph:
        if x.parent == None:
            dic[x.entity] = x.value
        else:
            curr = graph[x.parent]
            while curr.parent != None:
                curr = graph[curr.parent]
            dic[x.entity] = curr.value

    return dic


def create_questions(args, files_mapping):
    print('create_questions')
    keywords = read_pickle(get_file_name(args, 'keywords'))

    nlp = spacy.load('en')

    questions = {}
    i = 0
    for prefix in tqdm(files_mapping.keys(), total=len(files_mapping)):
        for man_made_file in keywords[prefix]:
            with open(os.path.join(args.data, man_made_file), encoding='cp1252') as file: 
                text = file.read()
                text = clean_text(text)
                doc = nlp(text)
                sentences = [sent for sent in doc.sents]

                for sent in sentences:
                    entities_asked_about_this_sent = []
                    curr_keywords = graph_to_dict(keywords[prefix][man_made_file])
                    for keyword, keyword_key in curr_keywords.items():
                        if keyword_key in entities_asked_about_this_sent: continue

                        answer = '@entity' + str(keyword_key)
                        question = entitize(sent, curr_keywords, keyword)
                        if '@placeholder' not in question: continue
                        if prefix not in questions:
                            questions[prefix] = {}
                        if man_made_file not in questions[prefix]:
                            questions[prefix][man_made_file] = []
                        question_splitted_by_spaces = ' '.join([w.text for w in nlp(question)])
                        questions[prefix][man_made_file].append({'question': question_splitted_by_spaces, 'answer': answer})
                        entities_asked_about_this_sent.append(keyword_key)

    write_pickle(get_file_name(args, 'questions'), questions)


def create_summaries_with_keywords(args, files_mapping):
    summaries_with_keywords_folder = get_file_name(args, 'summaries_with_keywords')
    print('create_summaries_with_keywords')

    nlp = spacy.load('en')

    keywords = read_pickle(get_file_name(args, 'keywords'))
    for prefix in tqdm(files_mapping.keys(), total=len(files_mapping)):
        for questioning_doc in keywords[prefix]:
            for answering_doc in files_mapping[prefix]['machine']:
                with open(os.path.join(args.data, answering_doc), encoding='cp1252') as original_file:
                    text = original_file.read()
                    text = clean_text(text)
                    doc = nlp(text)
                    curr_keywords = keywords[prefix][questioning_doc]
                    answering_doc_keywords = []
                    
                    for ent in doc.ents:
                        if ent.label_ in all_entities and ent.end_char - ent.start_char > 1:
                            answering_doc_keywords.append(ent.lemma_)
                    merged_keywords = graph_to_dict(merge(nlp, answering_doc_keywords, copy.deepcopy(curr_keywords)))
                    text = entitize(doc, merged_keywords)

                with open(os.path.join(summaries_with_keywords_folder ,answering_doc+'-for-'+questioning_doc), 'w', encoding='cp1252') as entitized_file:
                    entitized_file.write(text)

def entitize(doc, keywords, answer=None):
    
    keywords_as_list = sorted(keywords.keys(), key=lambda x: len(x), reverse=True) 
    text = lemmatize_questions_by_keywords(doc, keywords)

    for ent in keywords_as_list:
        ent_token = '@entity' + str(keywords[ent])
        text = re.sub(r'\b' + re.escape(ent) + r'\b', ent_token, text, flags=re.IGNORECASE)
    if answer is not None:
        text = re.sub(r'\b' + re.escape('entity' + str(keywords[answer])) + r'\b', 'placeholder', text, flags=re.IGNORECASE)

    return text

def lemmatize_questions_by_keywords(doc, keywords):
    text_as_list = [t.text for t in doc]
    for ent in keywords:
        for i, w in enumerate(doc):
            if w.lemma_ == ent:
                text_as_list[i] = ent
    text = ' '.join(text_as_list)
    return text

def clean_text(text):
    text = text.replace('.\n', '. ')
    text = text.replace('\n', ' ')
    text = text.replace('   ', ' ')
    text = text.replace('  ', ' ')
    text = text.replace('  ', ' ')
    text = text.replace("’", "'")
    text = re.sub("\'s", "", text) # we have cases like "Sam is" or "Sam's" (i.e. his) these two cases aren't separable, I choose to compromise are kill "'s" directly
    text = re.sub("s\'", "", text)
    text = re.sub(" whats ", " what is ", text, flags=re.IGNORECASE)
    text = re.sub("\'ve", " have ", text)
    text = re.sub("can't", "can not", text)
    text = re.sub("n't", " not ", text)
    text = re.sub("i'm", "i am", text, flags=re.IGNORECASE)
    text = re.sub("\'re", " are ", text)
    text = re.sub("\'d", " would ", text)
    text = re.sub("\'ll", " will ", text)
    text = re.sub("e\.g\.", " eg ", text, flags=re.IGNORECASE)
    text = re.sub("b\.g\.", " bg ", text, flags=re.IGNORECASE)
    text = re.sub(r"(\W|^)([0-9]+)[kK](\W|$)", r"\1\g<2>000\3", text) # better regex provided by @armamut
    text = re.sub("e-mail", " email ", text, flags=re.IGNORECASE)
    text = re.sub(r"\bu\.s\.a", "USA", text, flags=re.IGNORECASE)
    text = re.sub(r"\bu\.s\.", "USA", text, flags=re.IGNORECASE)
    text = re.sub(r"\busa\b", "USA", text, flags=re.IGNORECASE)
    text = re.sub(r"\bus\b", "USA", text, flags=re.IGNORECASE)
    text = re.sub("(the[\s]+|The[\s]+)?U\.S\.A\.", " USA ", text, flags=re.IGNORECASE)
    text = re.sub("(the[\s]+|The[\s]+)?United State(s)?", " USA ", text, flags=re.IGNORECASE)
    text = re.sub("Los angeles", "LA", text, flags=re.IGNORECASE)
    text = re.sub("\(s\)", " ", text, flags=re.IGNORECASE)
    return text

def get_file_name(args, name):
    if name == 'files_mapping':
        return'./files_mapping_file_'+str(args.run_name)+'.pkl'
    if name == 'entities':
        return'./entities_data'+str(args.run_name)+'.pkl'
    if name == 'top_tfidf_words':
        return'./top_tfidf_words_file'+str(args.run_name)+'.pkl'
    if name == 'verbs_and_nouns':
        return'./verbs_and_nouns_file_'+str(args.run_name)+'.pkl'
    if name == 'keywords':
        return'./keywords_file_'+str(args.run_name)+'.pkl'
    if name == 'questions':
        return'./questions_data_'+str(args.run_name)+'.pkl'
    if name == 'summaries_with_keywords':
        return 'summaries_with_keywords_'+str(args.run_name)

def main():
    parser = argparse.ArgumentParser(description='Creating Fill in the Blanks Type Questions')
    parser.add_argument('--run_name', required=True, type=str)
    parser.add_argument('--qa_id', type=int)
    parser.add_argument('--data_dir', type=int)

    args = parser.parse_args()

    files_mapping = create_files_mapping(args)
    
    create_entities(args, files_mapping)
    merge_keywords(args, files_mapping)
    create_questions(args, files_mapping)
    create_summaries_with_keywords(args, files_mapping)


if __name__ == "__main__":
   main()