package com.agentforge.shop.payment;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "shop.wechat-pay")
public class WechatPayProperties {
    private String merchantId;
    private String appId;
    private String apiV3Key;
    private String privateKeyPath;
    private String merchantSerialNumber;
    private String notifyUrl;
    public String getMerchantId(){return merchantId;} public void setMerchantId(String v){merchantId=v;}
    public String getAppId(){return appId;} public void setAppId(String v){appId=v;}
    public String getApiV3Key(){return apiV3Key;} public void setApiV3Key(String v){apiV3Key=v;}
    public String getPrivateKeyPath(){return privateKeyPath;} public void setPrivateKeyPath(String v){privateKeyPath=v;}
    public String getMerchantSerialNumber(){return merchantSerialNumber;} public void setMerchantSerialNumber(String v){merchantSerialNumber=v;}
    public String getNotifyUrl(){return notifyUrl;} public void setNotifyUrl(String v){notifyUrl=v;}
}
