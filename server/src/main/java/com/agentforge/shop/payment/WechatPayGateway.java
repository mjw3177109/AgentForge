package com.agentforge.shop.payment;

public interface WechatPayGateway {
    String createJsapiPrepay(long orderId, long amountFen, String openId);
}
