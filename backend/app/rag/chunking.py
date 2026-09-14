from langchain_text_splitters import RecursiveCharacterTextSplitter

def split_documents(documents, chunk_size=350, chunk_overlap=50):
    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size, chunk_overlap=chunk_overlap, length_function=len,
    ).split_documents(documents)
