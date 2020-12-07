import os
import json
import datetime
import numpy as np
import pandas as pd
import tensorflow as tf
from scipy import sparse
from sklearn.model_selection import KFold
from public import *

class _KDDCupDataProcessor:
    # minTimestamp必须传值，默认值不管用
    def __init__(self, userLC, problemLC, timeLC, drop_duplicates = True, remove_nan_skills = True, datasetName = 'algebra08', TmpDir = "./data/"):

        self.datasetName = datasetName

        self.LC_params={}
        self.LC_params['userLC'] = userLC
        self.LC_params['problemLC'] = problemLC
        self.LC_params['timeLC'] = transferStrT2Dir(timeLC)
        self.LC_params['dropDup'] = drop_duplicates
        self.LC_params['remoNanSkill'] = remove_nan_skills

        self.TmpDir = TmpDir
        self.RawDataDir = os.path.join(self.TmpDir, 'rawData', self.datasetName)
        self.RawDataName = 'data.txt'
        self.LCDataDir = os.path.join(self.TmpDir, 'LCData',self.datasetName+getLegend(self.LC_params))

        self.timeLC, self.minTimestamp = transferStrT2Seconds(timeLC)

    def loadLCData(self):

        # 所有的字典都是id2str

        flag = 0
        if not os.path.exists(os.path.join(self.LCDataDir, 'studentSubmitRecords.csv')):
            flag = 1
        if not os.path.exists(os.path.join(self.LCDataDir, 'QMatrix.npz')):
            flag = 1
        if not os.path.exists(os.path.join(self.LCDataDir, 'StaticInformation.json')):
            flag = 1
        if not os.path.exists(os.path.join(self.LCDataDir, 'userInformation.json')):
            flag = 1
        if not os.path.exists(os.path.join(self.LCDataDir, 'knowledgeInformation.json')):
            flag = 1
        '''
        if not os.path.exists(os.path.join(self.LCDataDir, 'UnitInformation.json')):
            flag = 1
        if not os.path.exists(os.path.join(self.LCDataDir, 'SectionInformation.json')):
            flag = 1
        '''


        if flag == 0:
            df = pd.read_csv(os.path.join(self.LCDataDir, 'studentSubmitRecords.csv'), sep='\t')
            QMatrix = sparse.load_npz(os.path.join(self.LCDataDir,'QMatrix.npz'))
            StaticInformation = loadDict(self.LCDataDir,'StaticInformation.json')
            userInformation = loadDict(self.LCDataDir,'userInformation.json')
            knowledgeInformation = loadDict(self.LCDataDir,'knowledgeInformation.json')
            DictList = [userInformation, knowledgeInformation]
            #UnitInformation = loadDict(self.LCDataDir,'UnitInformation.json')
            #SectionInformation = loadDict(self.LCDataDir,'SectionInformation.json')
            #DictList = [userInformation, knowledgeInformation, UnitInformation, SectionInformation]
            return df, QMatrix, StaticInformation, DictList

        prepareFolder(self.LCDataDir)

        if self.datasetName == 'algebra08':
            kc_col_name = 'KC(KTracedSkills)'

        df = pd.read_csv(os.path.join(self.RawDataDir, self.RawDataName), delimiter='\t', low_memory=False).rename(columns={
            'Anon Student Id': 'user_id',
            'Problem Name': 'pb_id',
            'Step Name': 'step_id',
            kc_col_name: 'kc_id',
            'First Transaction Time': 'timestamp',
            'Correct First Attempt': 'correct'
            })[['user_id', 'pb_id', 'step_id' ,'correct', 'timestamp', 'kc_id']]

        # 1 timeLC
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df['timestamp'] = df['timestamp'] - self.minTimestamp
        #df['timestamp'] = df['timestamp'].apply(lambda x: x.total_seconds() / (3600*24))
        df['timestamp'] = df['timestamp'].apply(lambda x: x.total_seconds()).astype(np.int64)
        #print(df['timestamp'].max(),self.LC_params['timeLC'][0],self.LC_params['timeLC'][1])
        df = df[df.timestamp >= self.timeLC[0]]
        df = df[df.timestamp <= self.timeLC[1]]

        # 2 userLC
        df = df.groupby('user_id').filter(lambda x: len(x) >= self.LC_params['userLC'][0])
        df = df.groupby('user_id').filter(lambda x: len(x) <= self.LC_params['userLC'][1])

        # 3 problemLC
        df = df.groupby('pb_id').filter(lambda x: len(x) >= self.LC_params['problemLC'][0])
        df = df.groupby('pb_id').filter(lambda x: len(x) <= self.LC_params['problemLC'][1])

        df.sort_values(by = 'timestamp', inplace = True)
        
        df['item_id'] = str(df['pb_id'])+':'+df['step_id']
        df = df[['user_id', 'item_id', 'kc_id', 'correct', 'timestamp']]

        # 这里的去重指的是一个人同时提交同一道题
        if self.LC_params['dropDup']:
            df.drop_duplicates(subset=['user_id', 'item_id', 'timestamp'], inplace=True)
        
        if self.LC_params['remoNanSkill']:
            df = df[~df['kc_id'].isnull()]
        else:
            df.ix[df['kc_id'].isnull(), 'kc_id'] = 'NaN'

        # Create list of KCs
        listOfKC = []
        for kc_raw in df["kc_id"].unique():
            for elt in kc_raw.split('~~'):
                listOfKC.append(elt)
        listOfKC = np.unique(listOfKC)

        dict1_kc = {}
        knowledgeInformation = {}
        for k, v in enumerate(listOfKC):
            dict1_kc[v] = k
            knowledgeInformation[k] = v

        userInformation = createDictBydf(df, 'user_id')
        itemInformation = createDictBydf(df, 'item_id')
        user2id = reverseDict(userInformation)
        item2id = reverseDict(itemInformation)

        # Transform ids into numeric
        df['user_id'] = df['user_id'].apply(lambda x: user2id[x])
        df['item_id'] = df['item_id'].apply(lambda x: item2id[x])

        # Build Q-matrix
        QMatrix = np.zeros((len(df['item_id'].unique()), len(listOfKC)))
        item_skill = np.array(df[['item_id','kc_id']])
        for i in range(len(item_skill)):
            splitted_kc = item_skill[i,1].split('~~')
            for kc in splitted_kc:
                QMatrix[item_skill[i,0],dict1_kc[kc]] = 1
        numKCs = str(QMatrix.tolist()).count("1")

        df = df[['user_id', 'item_id', 'timestamp', 'correct']]
        df = df[df.correct.isin([0,1])] # Remove potential continuous outcomes
        df['correct'] = df['correct'].astype(np.int32) # Cast outcome as int32

        StaticInformation = {}
        StaticInformation['userNum'] = len(df['user_id'].unique())
        StaticInformation['itemNum'] = len(df['item_id'].unique())
        StaticInformation['knowledgeNum'] = len(listOfKC)
        StaticInformation['recordsNum'] = df.shape[0]

        StaticInformation['aveUserSubmit'] = df.shape[0] / len(df['user_id'].unique())
        StaticInformation['aveitemNumSubmit'] = df.shape[0] / len(df['item_id'].unique())
        StaticInformation['aveItemContainKnowledge'] = numKCs / len(df['item_id'].unique())

        #DictList = [userInformation, knowledgeInformation, UnitInformation, SectionInformation]
        DictList = [userInformation, knowledgeInformation]

        # Save data
        sparse.save_npz(os.path.join(self.LCDataDir,'QMatrix.npz'), sparse.csr_matrix(QMatrix))
        df.to_csv(os.path.join(self.LCDataDir,'studentSubmitRecords.csv'), sep='\t', index=False)
        saveDict(StaticInformation,self.LCDataDir,'StaticInformation.json')
        saveDict(userInformation,self.LCDataDir,'userInformation.json')
        saveDict(knowledgeInformation,self.LCDataDir,'knowledgeInformation.json')
        saveDict(self.LC_params,self.LCDataDir,'parameters.json')
        #saveDict(UnitInformation,self.LCDataDir,'userInformation.json')
        #saveDict(SectionInformation,self.LCDataDir,'userInformation.json')

        return df, QMatrix, StaticInformation, DictList



'''
userLC = [10,100]
problemLC = [10,100]
#algebra08原始数据里的最值，可以注释，不要删
low_time = "2008-09-08 14:46:48"
high_time = "2009-07-06 18:02:12"
timeLC = [low_time, high_time]
a = _KDDCupDataProcessor(userLC, problemLC, timeLC)
print('**************LC_params**************')
printDict(a.LC_params)
[df, QMatrix, StaticInformation, DictList] = a.loadLCData()
print('**************StaticInformation**************')
printDict(StaticInformation)
'''



