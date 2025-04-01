# -*- coding: utf-8 -*-

#distance calculations
import math 
#csv reading
import pandas as pd 
#not currently needed, here for convenience 
#as I've used it before switching datasources
import geopandas as gpd 
#not currently needed, likewise here for convenience
from shapely.geometry import Point 
#not currently needed, here for convenience
from datetime import datetime 
#not currently needed, here for convenience
import contextily as cx
#distance calculations and df comparisons
import numpy as np


#the city under consideration, if following the methods from the paper:
cityName='Atlanta'
#city boundaries:
#for example, here is the bounding box which includes the I-285 interstate, which circles Atlanta
# used by the functions called for matrix manipulation   
maxlongitude=-84.227909
minlongitude=-84.505798
maxlatitude=33.923198
minlatitude=33.613440


cityName='Denver' 
maxlongitude=-104.728302
minlongitude=-105.232186
maxlatitude=39.972504
minlatitude=39.555531


class Main():     

    def __init__(self):

        #main files:

        #commuter info downloaded from LODES, unzipped. 
        #specifically, [state]_od_main_JT00_[year].csv
        self.csvfile = "co_od_main_JT00_2020.csv"

        #the crosswalk file given with the LODES data
        self.xwalk="co_xwalk.csv"

        #customer info, with location data & some names for convenience
        #if running preprocess(), this is the place where it will be saved
        self.custfile='COCustomers.csv' #origin ID, dest ID, # commuters traveling between them, info on districts

        #station info, made from the tract locations
        #if running preprocess(), this is the place where it will be saved
        self.statfile='COStations.csv' #station ID, location

        #every valid pair of station & commuter; the function that creates this will 
        #if running preprocess(), this is the place where it will be saved
        self.pairfile='COPairs.csv' #customer ID, station ID, distance


        #parameters, preset here to recommended values:

        #set this to True if working with smaller dataset as test set:
        #only commuters who both live and work inside the perimeter are included
        self.bitesize=False 

        #if true, aggregate to tracts from blocks, and use tracks
        #whenever relevant; otherwise solve in blocks
        self.aggregate=True 

        #additional inputs:
        #(only for Atlanta)
        self.homefile='GAFPL2018.csv' #home statistics 

        


    def preprocess(self):
        #creates all three files (commuter information ('custfile'), station information ('statfile'), and pairwise distances ('pairfile'))
        #saves to locations in __init__
        self.write_data()
        pairs=self.format_pair()
        pairs.to_csv(self.pairfile)

    def write_data(self):
        #preprocessing without home charging information, and without creating pairfile

        #filters LODES data into relevant commuter data, and, if self.aggregate,
        #also aggregates these into census tracts from blocks
        cust=self.format_cust()
        cust.to_csv(self.custfile)

        #uses self.custfile to create a list of potential station locations with IDs and 
        #lat/long locations
        stat=self.format_stat()
        stat.to_csv(self.statfile)
        #there is one more file that the optimization will require, here referred to mostly as 
        #pairfile, but it requires a fair bit of ram as written; 
        #format_pair() documents the math performed
    
    def format_cust(self):
        #take original LODES data at census block level from self.csvfile
        #output origin info, destination info, and number of commuters traveling route

        #if self.aggregate, output data will be aggregated into census tracts

        #the location returned for the aggregated tracts is the linear average of the 
        #latitude/longitudes of the centroids of the component blocks

        #read & hold origin and destination info
        origins=self.format_districts(orig=True)     
        dests=self.format_districts(orig=False)


        #file with origin-destination commuter data
        cols=['w_geocode','h_geocode','S000']
        csvframe=pd.read_csv(self.csvfile, usecols=cols,dtype={'w_geocode':str,'h_geocode':str})
        
        #origin, destination, and tot. num. commuters
        csvframe=csvframe[['w_geocode','h_geocode','S000']]
        
        #rename columns for clarity
        mapp=dict()
        mapp['w_geocode']='Work ID'
        mapp['h_geocode']='Home ID'
        mapp['S000']='Commuters'
        csvframe=csvframe.rename(columns=mapp)

        if self.aggregate:

            #change to tract id; set as string for concatenation
            csvframe['Home ID'] = csvframe['Home ID'].str[0:11] 
            csvframe['Work ID'] = csvframe['Work ID'].str[0:11]

            #combined label for origin and destination as a string
            csvframe['OrigDest'] = csvframe['Home ID']+csvframe['Work ID']



            #sum over tract ids
            commutes=csvframe[['OrigDest','Commuters']].groupby(['OrigDest']).sum()
            #put new aggregated column in with IDs
            csvframe=csvframe[['OrigDest','Home ID','Work ID']]
            csvframe=csvframe.drop_duplicates()
            csvframe=pd.DataFrame(csvframe)
            csvframe=commutes.merge(csvframe,on='OrigDest',how='inner')
            del commutes
        

        #add info on orig and destination tracts/blocks
        print(origins.head())
        print(csvframe.head())
        odframe=origins.merge(csvframe,on='Home ID',how='inner')
        del csvframe
        odframe=dests.merge(odframe,on='Work ID',how='inner')
        del origins
        del dests
        
        odframe.index.name='Customer ID'

        #distance between origin and destination
        odframe['Travel Distance'] = odframe.apply(td,axis=1)
        #is origin OR destination in ATL? (the set of data used in the paper)
        odframe[cityName]=odframe.apply(bigCity,axis=1)
        #are origin AND destination in ATl? (a smaller set for testing)
        odframe['Small Set']=odframe.apply(smallCity,axis=1)
        
        if True: #output ONLY Atl (paper) data
            odframe=odframe.loc[odframe[cityName]==1]
        if self.bitesize: #output ONLY small testing data
            odframe=odframe.loc[odframe['Small Set']==1]
        
        return odframe
    
    def format_stat(self):
        #read in original LODEs data
        #output list of potential stations and locations (one per tract/block)

        #if self.aggregate, aggregate into tracts as with commuters

        stations=self.format_districts(station=True)
        stations.index.name='ID'

        
        
        if True: #output only stations near Atl
            stations[cityName]=stations.apply(nearCity,axis=1)
            stations=stations.loc[stations[cityName]==1]
        else: #output all stations w/ additional binary column =1 if in Atl
            stations[City]=stations.apply(statCity,axis=1)
        
        return stations

        
    def format_districts(self,orig=True,station=False):
        #pulls location and name data from crosswalk file
        #outputs ID, tract/block info
        
        #orig: output w/ column labels for 'home'
        #false: output w/ column labels for 'work'
        #station: disregard 'origin'; output w/ column labels for 'station'
        #a silly way to handle column names but if it works, don't break it ;)
        #this isn't a function you're likely to call directly

        #start: location for col labels
        if orig:
            start='Home'
        else:
            start='Work'  
            
        if station:
            start='Station'
        
        #aggregate--use tract info; else use block info
        if self.aggregate:
            cols=['trct']
            tdict={'trct':str}
        else:
            cols=['tabblk2020']
            tdict={'tabblk2020':str}

        #name for tract location, long and lat, name of county
        cols=cols+['stwibname','blklondd','blklatdd','ctyname']
        
        #file with geodata for census tracts
        districts = pd.read_csv(self.xwalk, usecols=cols,dtype=tdict)


        #rename columns before merging for clarity
        mapp=dict()
        names=[start+' ID',start+' Name',start+' Longitude',start+' Latitude',start+' County']
        ID,sd,x,y,cty=names
        if self.aggregate:
            mapp['trct']=ID
        else:
            mapp['tabblk2020']=ID
        mapp['stwibname']=sd
        mapp['blklondd']=x
        mapp['blklatdd']=y
        mapp['ctyname']=cty
        districts=districts.rename(columns=mapp)
        districts=districts[names]

        #aggregation into tracts
        if self.aggregate:
            #str info (trct id, countyname, area name)
            miscinfo=districts[[ID,sd,cty]]
            miscinfo=miscinfo.drop_duplicates(subset=[ID])

            #average to get new 'center' of tract 
            districts=districts[[ID,x,y]].groupby(ID).mean()
            districts=pd.DataFrame(districts)

            #add back in str info
            districts=districts.merge(miscinfo,on=ID)
            
        return districts
    
    def format_pair(self):
        #take customer info and station info from self.custfile and self.statfile
        #output cust ID, station ID, and distance between every pair of cust and stat id in both files
        #into self.pairfile
        #(note that this does not filter, so do not expect it to)

        #this is too large to run with the paper's dataset on my run-of-the-mill laptop;
        #I performed the same math, but with multithreading, on a stronger computer

        #this does, however, work for smaller datasets to generate a testing set
        #and is included here both for that purpose and as documentation
        
        #read from (generated, not original) csv the lats & longs
        cols=['Customer ID','Work Latitude','Work Longitude','Home Latitude','Home Longitude']
        custs=pd.read_csv(self.custfile, usecols=cols)
        #likewise for stations
        cols=['ID','Station Latitude','Station Longitude']
        stats=pd.read_csv(self.statfile,usecols=cols)
        stats.rename(columns={'ID':'Station ID'}, inplace = True)
        
        #combine into commuters x stations
        pairs=custs.merge(stats,how='cross')
        
        #distance calculation
        pairs['Distance']=pairs.apply(pairDist,axis=1)
        #removing excess columns (lat and long) to reduce final csv size
        pairs=pairs[['Customer ID','Station ID','Distance']]

        return pairs
    


    def home_charging(self):
        #take premade customer file, add home charging percentages, output modified dataframe

        #pull just the home info--dataframe with 
        #tract id, type of building, # units
        #left out some columns so this will have tracts split into several entries
        cols=['FIP','BLD','UNITS']
        df=pd.read_csv(self.homefile,usecols=cols)

        #% of customers who do NOT have home charging access
        apt=1-0.091
        percents={
            '1 UNIT DETACHED':1-0.783, 
            '1 UNIT ATTACHED':1-0.076,
            '2 UNIT': apt,
            '3-4 UNIT':apt,
            '5-9 UNIT': apt,
            '10-19 UNIT': apt,
            '20-49 UNIT': apt,
            '50+ UNIT': apt,
            'BOAT RV VAN':0,
            'MOBILE TRAILER':0
        }

        #weighted = number of units without access to home charging
        df['Weighted']=df['UNITS']
        for (build,perc) in percents.items():
            df.loc[df['BLD']==build,'Weighted']=df[df['BLD']==build]['UNITS']*perc

        #leave out 'other' from the unit types
        df.loc[~df['BLD'].isin(percents.keys()),'Weighted']=0

        #combine entries for ea. tract
        dfagg=df[['FIP','UNITS','Weighted']].groupby(['FIP']).sum().reset_index()

        #divide to get percentage for output file
        dfagg['Percent w/o Level 1']=dfagg['Weighted']/dfagg['UNITS']
        print(dfagg['Percent w/o Level 1'].min(), dfagg['Percent w/o Level 1'].max())

        #remove 'weighted' and 'units' as we will not need them
        df=dfagg[['FIP','Percent w/o Level 1']]
        df.rename(columns={'FIP':'Home ID'}, inplace = True)

        #combine with original cust file
        cdf=pd.read_csv(self.custin)
        cdf=cdf.merge(df,on='Home ID',how='left')

        #if no data, make sure it's nan (some are 0s)
        cdf['Percent w/o Level 1'].replace(0,np.nan, inplace=True)
        #calc avg percent without charging
        tdf=cdf
        tdf['Weighted']=tdf['Commuters']*tdf['Percent w/o Level 1']
        totc=tdf.loc[~tdf['Percent w/o Level 1'].isna(),'Commuters'].sum()
        avgpercent=tdf['Weighted'].sum()/totc
        del tdf
        #replace empty entries (should now all be nan) with avg percent
        cdf['Percent w/o Level 1'].replace(np.nan,avgpercent, inplace=True)
        cdf['Commuters w/o Level 1']=cdf['Commuters']*cdf['Percent w/o Level 1']

        return cdf
    
def lldist(lat1, long1, lat2, long2):

    # Convert latitude and longitude to
    # spherical coordinates in radians.
    degrees_to_radians = math.pi/180.0

    # phi = 90 - latitude
    phi1 = (90.0 - lat1)*degrees_to_radians
    phi2 = (90.0 - lat2)*degrees_to_radians

    # theta = longitude
    theta1 = long1*degrees_to_radians
    theta2 = long2*degrees_to_radians

    # Compute spherical distance from spherical coordinates.
    
    # For two locations in spherical coordinates
    # (1, theta, phi) and (1, theta', phi')
    # cosine( arc length ) =
    # sin phi sin phi' cos(theta-theta') + cos phi cos phi'
    # distance = rho * arc length
    
    cos = (math.sin(phi1)*math.sin(phi2)*math.cos(theta1 - theta2) +
    math.cos(phi1)*math.cos(phi2))
    if cos>1:
        cos=1
    arc = math.acos( cos )
    arc=arc*3958.8

    return arc

def statCity( row ):
    #simple function: is a given station (in a dataframe with correct col names) in Atl? 0/1
    olon=row['Station Longitude']
    olat=row['Station Latitude']
  
    return inCity(olat,olon)
    

def inCity(lat,lon):
    #is a given latitude/longitude pair inside the city perimeter rectangle? 0/1

    if lat>=minlatitude and lat <= maxlatitude and lon >= minlongitude and lon <= maxlongitude:
        return 1
    else:
        return 0

def td( row ):
    #calculates distance a commuter travels round-trip
    #from a dataframe row with correct column names
    #does NOT add any additional travel distance
    ox=row['Home Longitude']
    oy=row['Home Latitude']
    dx=row['Work Longitude']
    dy=row['Work Latitude']
  
    toreturn=abs(lldist(oy,ox,dy,dx))
    toreturn=2*toreturn
    toreturn=math.ceil(toreturn)

    return toreturn

def bigCity( row ):
    #is a commuter's home or work location in the city? 0/1
    #given the commuter's row in a dataframe
    olon=row['Home Longitude']
    olat=row['Home Latitude']
    dlon=row['Work Longitude']
    dlat=row['Work Latitude']
  
    if inCity(olat,olon)==1 or inCity(dlat,dlon)==1:
        return 1
    else:
        return 0

def smallCity( row ):
    #are a commuter's home and work locations both in the city? 0/1
    #given the associated row in a dataframe
    olon=row['Home Longitude']
    olat=row['Home Latitude']
    dlon=row['Work Longitude']
    dlat=row['Work Latitude']
  
    if inCity(olat,olon)==1 and inCity(dlat,dlon)==1:
        return 1
    else:
        return 0
    
def pairDist(row):
    #calculate the distnace between a commuter and a station, given the associated row in 
    #a dataframe
    olon=row['Home Longitude']
    olat=row['Home Latitude']
    dlon=row['Work Longitude']
    dlat=row['Work Latitude']
    slat=row['Station Latitude']
    slon=row['Station Longitude']
    
    #distance to station for commuter is mininmum of distance to station from home and from work
    d1=lldist(olat, olon, slat, slon)
    d2=lldist(dlat,dlon,slat,slon)
    d= min(d1,d2)
    d=math.ceil(d)
    return d

def nearCity(row):
    #is a station near the centerpoint of the city
    alat=(maxlatitude+minlatitude)/2
    alon=(minlongitude+maxlongitude)/2
    slon=row['Station Longitude']
    slat=row['Station Latitude']
    d=lldist(alat, alon, slat, slon)
    if d>50:
        return 0
    else:
        return 1
    
    
main=Main()
main.preprocess()
