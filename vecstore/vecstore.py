
from langchain.vectorstores import Chroma
from langchain.embeddings.openai import OpenAIEmbeddings
from langchain.chat_models import AzureChatOpenAI
from langchain.chains import RetrievalQA
import gradio as gr
import pandas as pd

def _init():
    global vec_store
    vec_store = Chroma()

def create_vectorstore(persist_vec_path:str):
    '''
    Create vectorstore.
    '''
    if persist_vec_path == "":
        raise gr.Error("Please provide a path to persist the vectorstore.")
    
    import os
    if os.path.isabs(persist_vec_path):
        embeddings = OpenAIEmbeddings()

        # global vectorstore
        vectorstore = Chroma(persist_directory=persist_vec_path,embedding_function=embeddings)
        vectorstore.persist()
    else:
        raise gr.Error("The path is not valid.")
    
    return vectorstore

def add_file_in_vectorstore(persist_vec_path:str, 
                            split_docs:list,
                            file_obj,   # get it from 'file' (gr.file)
                            progress=gr.Progress()
                            ):
    '''
    Add file to vectorstore.
    '''

    if file_obj == None:
        raise gr.Error("You haven't chosen a file yet.")

    if persist_vec_path:
        global vectorstore
        vectorstore = Chroma(persist_directory=persist_vec_path, 
                             embedding_function=OpenAIEmbeddings())
    else:
        raise gr.Error("You haven't chosen a knowledge base yet.")
    
    # Before we add file, we should detect if there is a file with the same name
    import os
    
    # New file's name
    file_absolute_path = file_obj.name
    print(file_absolute_path)
    file_name = os.path.basename(file_absolute_path)
    
    vct_store = vectorstore.get()
    unique_sources = set(vct_store['metadatas'][i]['source'] for i in range(len(vct_store['metadatas'])))
    progress(0.3, desc="Updating knowledge base...")
    
    # List of names of files in kownledge base
    vec_file_names = [source.split('/')[-1].split('\\')[-1] for source in unique_sources]

    # Compare file_name with vec_file_names
    if file_name in vec_file_names: 
        raise gr.Error('File already exists in vectorstore.')
    
    # If file is already exist, it won't be added repeatedly
    vectorstore.add_documents(documents=split_docs[-1])
    progress(1, desc="Adding the file to the knowledge base...")
    return gr.DataFrame(),gr.Dropdown()

# def save_vectorstore(vectorstore:Chroma):
#     '''
#     Save vectorstore.
#     '''
#     vectorstore.persist()

def delete_flie_in_vectorstore(file_list,
                               progress=gr.Progress()
                               ):
    '''
    Get the file's ids first, then delete by vector IDs.
    '''

    # Specify the target file
    try:
        metadata = vectorstore.get()
    except NameError as n:
        raise gr.Error('Vectorstore is not initialized.')

    # Initialize an empty list to store the ids
    ids_for_target_file = []

    # Loop over the metadata
    for i in range(len(metadata['metadatas'])):
        # Check if the source matches the target file
        # We only compare the last part of the path (the actual file name)
        if metadata['metadatas'][i]['source'].split('/')[-1].split('\\')[-1] == file_list:
            # If it matches, add the corresponding id to the list
            ids_for_target_file.append(metadata['ids'][i])

    progress(0.9, desc="Document comparison in progress...")

    # print("IDs for target file:", ids_for_target_file)
    try:
        vectorstore.delete(ids=ids_for_target_file)
        progress(1, desc="File deleting...")
        gr.Info("The selected file has been deleted")
    except ValueError as v:
        raise gr.Error('File does not exist in vectorstore.')
    return


def load_vectorstore(persist_vec_path:str):
    '''
    Load vectorstore, and trun the files' name to dataframe.
    '''
    global vectorstore

    if persist_vec_path:
        vectorstore = Chroma(persist_directory=persist_vec_path, 
                             embedding_function=OpenAIEmbeddings())
    else:
        raise gr.Error("You didn't provide an absolute path to the knowledge base")

    vct_store = vectorstore.get()
    unique_sources = set(vct_store['metadatas'][i]['source'] for i in range(len(vct_store['metadatas'])))

    # Merge duplicate sources
    merged_sources = ', '.join(unique_sources)

    # Extract actual file names
    file_names = [source.split('/')[-1].split('\\')[-1] for source in unique_sources]

    df = pd.DataFrame(file_names, columns=['文件名称'])

    gr.Info('Successfully load kowledge base.')
    return df,gr.Dropdown(choices=file_names)

def refresh_file_list(df):
    '''
    abandon temporarily
    '''
    file_list = df['文件名称'].tolist()
    gr.Info('Successfully update kowledge base.')
    return gr.Dropdown.update(choices=file_list)

def find_source_paths(filenames, data):
    '''
    Retrieve file paths in a vector database based on file name and remove duplicate paths
    '''
    paths = []
    for metadata in data['metadatas']:
        source = metadata.get('source')
        if source:
            for filename in filenames:
                if filename in source and source not in paths:
                    paths.append(source)
    return paths

def ask_file(file_ask_history_list:list,
            question_prompt: str,
            file_answer:list,
            model_choice:str,
            sum_type:str,
            persist_vec_path,
            file_list
            ):
    '''
    send splitted file to LLM
    '''
    llm = AzureChatOpenAI(model=model_choice,
                    openai_api_type="azure",
                    deployment_name=model_choice, 
                    temperature=0.7)
    
    source_data = vectorstore.get()
    filter_goal = find_source_paths(filenames=file_list,data=source_data)

    if persist_vec_path != None:
        # docsearch = Chroma.from_documents(split_docs[-1], embeddings)
        if file_list == "Unselect file(s)" or file_list != None:    
            # unselect file: retrieve whole knowledge base
            try:
                qa = RetrievalQA.from_chain_type(llm=llm, chain_type=sum_type, 
                                                    retriever=vectorstore.as_retriever(search_type="mmr"), 
                                                    return_source_documents=True)
                result = qa({"query": question_prompt})
            except (NameError):
                raise gr.Error("You have not load kownledge base yet.")
        else:
            # only selected one file
            # Retrieve the specified knowledge base with filter
            qa = RetrievalQA.from_chain_type(llm=llm, chain_type=sum_type, 
                                                retriever=vectorstore.as_retriever(search_type="mmr",search_kwargs={'filter': {"source":filter_goal[0]}}), 
                                                return_source_documents=True)
            
            # get chain's result
            result = qa({"query": question_prompt})

        usr_prob = result["query"]
    # if there is no file, let it become a common chat model
    else:
        gr.Info("You don't select your knowledge base, so the result is presented by base model.")
        result = llm(question_prompt)+"\n引用文档："
        usr_prob = question_prompt
    file_answer[0] = result
    file_ask_history_list.append([usr_prob,None])
    return file_ask_history_list,file_answer

def find_source_paths(filenames:list, data):
    """
    Find the source paths of the files in the knowledge base.
    """
    paths = []
    for metadata in data['metadatas']:
        source = metadata.get('source')
        if source:
            for filename in filenames:
                if filename in source and source not in paths:
                    paths.append(source)
    return paths