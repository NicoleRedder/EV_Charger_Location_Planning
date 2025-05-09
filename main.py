
# -*- coding: utf-8 -*-

#included for convenience, as this was previously used
import random 
#floor function
import math
#modeling
from gurobipy import GRB,Model,quicksum
#not needed but included for convenience
import gurobipy
#data reading & writing
import pandas as pd
import geopandas as gpd
#previously used, included for convenience
from shapely.geometry import Point
#previously used, included for convenience
from datetime import datetime
#import mem_restrict  
#vector math & comparisons
import numpy as np



class Main():
    
    def __init__(self):
        #initializes with default values for the major parameters
        #these can be changed here, or after creating an instance
        
        #radius commuters are willing to travel to charger (in miles)
        self.r=1 
        #aggregate to census tracts (vs. leave as blocks)
        self.aggregate=True 
        #number of stations allowed to open, if variable
        self.B=50 
        #add constraint for equity?
        # 0: do not add
        # 1: at least 40% of stations are placed in disadvantaged areas
        # 2: at least 40% of commuters served are disadvantaged 
        self.eqconstr=0 
        #scale to only commuters who can't charge at home?
        self.hc=True 

        #input files:

        #columns required:
        # 'Customer ID' ids for viable commuter types (should be a valid key)
        # 'Commuters' number of commuters estimated to exist of the commuter type
        #  'Travel Distance' distance in miles the commuter type travels daily
        # 'Commuters w/o Level 1' number of estimated commuters existing of the commuter type who do 
        # not have access to home charging
        # 'Home ID' id for home tract (fips id) of commuter type
        #'Home ID' can be ommitted if not using equity constraints (self.eqconstr==0)
        #my custfile also includes latitude/longitude and name data for both 'work' and 'home', which 
        #may be useful for analysis of results
        self.custfile='commuters.csv'
        #columns required: 'ID' --station ids for all viable station locations
        #my statfile also includes latitude/longitude information, which may be useful for analysis
        self.statfile='stations.csv'
        #columns required: 'Customer ID','Station ID','Distance'
        self.pairfile='pairs.csv'
        #columns required: 
        # '2020 ID' cencus fips id from 2020
        # 'Disadvantaged' 0/1 whether community is disadvantaged
        self.eqfile='communities.csv'

        #default output files:
        #station placements
        self.zfile='AtlZ-2sd-model2.csv'
        #commuter assignments
        self.xfile='AtlX-2sd-model2.csv'
        
    
    def ip(self, justModel=True, version=2, z_ub=100):
        #justModel: output created gurobipy model, do not run
        #False: run model and save data to file instead

        #version=model number to use
        #1: serve as many customers as possible with limited stations
        #2: serve all customers with as few stations as possible

        #self.hc: if True, use only commuters who can't charge at home
        #if False, serve all commuters, even home chargers

        #self.eqconstr: #add constraint for equity?
        # 0: do not add
        # 1: at least 40% of stations are placed in disadvantaged areas
        # 2: at least 40% of customers served are disadvantaged  
        # 3: 2, with the binary logic that, if all disadvantaged commuters are served, the percentage need not apply
        
        
        #read necessary data

        #commuters w/o o-d numbers
        cols=['Customer ID','Commuters', 'Travel Distance']

        if self.eqconstr>0: #home id for equity reference
            cols=cols+['Home ID']            
        if self.hc: #home charging info
            cols=cols+['Commuters w/o Level 1']

        custs= pd.read_csv(self.custfile, usecols=cols) 

        #o-d numbers of commuters
        cols=['Customer ID','Station ID','Distance']
        pairs= pd.read_csv(self.pairfile,usecols=cols)   
        pairs=pairs.loc[pairs['Distance']<=self.r]  
        
        m=Model()
        
        #list of indices for easier refernce
        stations=pairs['Station ID'].unique()
        stations=stations.tolist()
        customers=custs['Customer ID'].unique()
        customers=customers.tolist()


        #xij: # customers of type i assigned to station j
        x=dict()
        for i in customers:
            x[i]=dict()
            S=pairs.loc[pairs['Customer ID']==i]
            for index, row in S.iterrows():
                x[i][row['Station ID']] =m.addVar(name='x_'+str(i)+'_'+str(row['Station ID']))        
        
        #zj: # chargers opened at location j
        z = dict()
        for j in stations:
            z[j]=m.addVar(name='z_'+str(j),vtype=GRB.INTEGER,ub=z_ub)
    
        #each charger is assigned at most mm customers
        mm=250*6*1 #num customer miles a single charger can serve:
            #250 miles per charge
            #1 hr to charge to full
            #18 hours-ish each station runs

        td=dict()
        for i in customers:
            a=custs.loc[custs['Customer ID']==i]['Travel Distance']
            a=a.tolist()
                    
            td[i]=a[0]+23
            
        #stations can charge at most mm * num chargers miles
        for j in stations:
            temp=pairs.loc[pairs['Station ID']==j]
            sj=temp['Customer ID'].unique().tolist()
            if len(sj)>0:    
                m.addConstr( (quicksum(td[i]*x[i][j] for i in sj)) <= z[j]*mm)
                
          
        #at most B stations created
        if version == 1:
            m.addConstr( (quicksum(z[j] for j in stations)) <= self.B)
        
        #customer upper bounds
        for i in customers:
            if not self.hc:
                upper=custs.loc[custs['Customer ID']==i]['Commuters']
            else:
                upper=custs.loc[custs['Customer ID']==i]['Commuters w/o Level 1']

            upper=upper.tolist()
            upper=upper[0]

            upper=round(upper, 0)

            temp=pairs.loc[pairs['Customer ID']==i]
            si=temp['Station ID'].unique().tolist()
            if len(si)>0:
                if version ==2:
                    #serve all customers
                    m.addConstr( (quicksum(x[i][j] for j in si)) >= upper)
                elif version ==1:
                    #upper bound is # commuters that actually exist
                    m.addConstr( (quicksum(x[i][j] for j in si)) <= upper)

        #equity type of constraints
        if self.eqconstr>0:
            cols=['2020 ID','Disadvantaged']
            df=pd.read_csv(self.eqfile,usecols=cols)

            if self.eqconstr==1:

                sdf=pd.read_csv(self.statfile,usecols=['ID','Station ID'])
                df.rename(columns={'2020 ID':'Station ID'}, inplace = True)
                df=df.merge(sdf,on='Station ID')
                dStations=dict()
                for j in stations:
                    disad=df[df['ID']==j]['Disadvantaged'].iloc[0]
                    if disad:
                        dStations[j]=1
                    else:
                        dStations[j]=0
                #at least 40% of stations must be in disadvantaged tracts
                m.addConstr( (quicksum(z[j]*dStations[j] for j in stations)) >= 0.4*(quicksum(z[j] for j in stations)))
            
            elif self.eqconstr in [2,3]: #at least 40% of commuters served must live in disadvantaged tracts
                df.rename(columns={'2020 ID':'Home ID'}, inplace = True)
                dCust=dict()
                df=custs.merge(df,on='Home ID',how='left')
                c_d = 0
                c_t = 0
                for i in customers:
                    disad=df[df['Customer ID']==i]['Disadvantaged'].iloc[0]
                    commutes=df[df['Customer ID']==i]['Commuters'].iloc[0]
                    if disad:
                        dCust[i]=1
                        c_d=c_d+commutes
                        c_t=c_t+commutes
                    else:
                        dCust[i]=0
                        c_t=c_t+commutes
                if self.eqconstr==2:
                    m.addConstr( (quicksum( (quicksum(x[i][j]*dCust[i] for j in x[i].keys())) for i in customers))>= 0.4*(quicksum( (quicksum(x[i][j] for j in x[i].keys())) for i in customers)))
                if self.eqconstr==3:
                    y=m.addVar(vtype=GRB.BINARY,name='y')
                    m.addConstr( (quicksum( (quicksum(x[i][j]*dCust[i] for j in x[i].keys())) for i in customers)) + (0.4*c_t * y)>= 0.4*(quicksum( (quicksum(x[i][j] for j in x[i].keys())) for i in customers)))
                    m.addConstr( (quicksum( (quicksum(x[i][j]*dCust[i] for j in x[i].keys())) for i in customers))>= 0.4*c_d*y)
            

            del df
        
        #maximize customers served
        if version ==1:
            m.setObjective( (quicksum( (quicksum(x[i][j] for j in x[i].keys())) for i in customers)), GRB.MAXIMIZE)
        
        #minimize stations needed            
        elif version ==2:
            m.setObjective( (quicksum(z[j] for j in z.keys())), GRB.MINIMIZE)
        
        #solve to within 1% of optimality
        m.setParam('MIPGap',0.01)
        if justModel: 
            #return the model object; do not solve it
            return m
        
        del custs
        del pairs

        #actual run of model
        m.optimize()
        
        #retrieve and save station placements
        optzs=[['Name','i','z_i']]
        for i in stations:
            zstar=z[i].x
            if zstar>0: #leave out unopened stations
                temp=[z[i].VarName,i,zstar]
                optzs.append(temp)
        df=pd.DataFrame(optzs)
        df.to_csv(self.zfile)
        
        #commuter assignments to stations
        optxs=[['Name','i','j','x_ij']]
        for i in customers:
            for j in x[i].keys():
                xstar=x[i][j].x
                if not self.hc:
                    xstar=math.floor(xstar)
                if xstar>0: #leave out unassigned commuters
                    optxs.append([x[i][j].VarName,i,j,xstar])
        df=pd.DataFrame(optxs)
        df.to_csv(self.xfile)

        return m.ObjVal
  



'''
#example
main=Main()
#here we can change parameters
main.B=4115
main.eqconstr=0
#run model and output results into m.xfile,m.zfile
m=main.ip(False, version = 2)
#print optimal value
print(m)'''




main=Main()

main.eqconstr=0
main.xfile='model2-noUB-x.csv'
main.zfile='model2-noUB-z.csv'
main.hc=False

#run model and output results into m.xfile,m.zfile
m=main.ip(False, version = 2,z_ub=1000)
#print optimal value
print(m)

